"""收集屏幕上看得见、能交互的界面元素（UI Automation）。

所有函数都在 DesktopWorker 的单线程中同步调用：该线程已初始化 COM，并设置了线程级
PerMonitorV2 DPI 感知，因此 UIA 返回的 BoundingRectangle 与 Win32 坐标都是物理像素。

实现要点：
- 直接使用 IUIAutomation 原生接口 + CacheRequest：每个容器只发一次跨进程调用，
  就能拿到全部子元素及其所需属性，避免逐个属性跨进程读取；
- 遍历时按矩形剪枝（整块不在可见范围内的子树直接跳过），并随时检查超时，
  Chrome / VS Code 这类巨型 UI 树也能在 timeout 内返回已收集的部分；
- 遮挡判定：对元素中心点调用 WindowFromPoint，所属根窗口必须就是元素所在的顶层窗口。

部分思路参考 Windows-MCP 0.8.1（MIT License, https://github.com/CursorTouch/Windows-MCP）：
- tree/config.py 的可交互控件类型集合与 LegacyIAccessible 默认动作集合；
- tree/cache_utils.py 用 BuildUpdatedCache(TreeScope_Children) + GetCachedChildren 批量取子元素；
- tree/service.py 对浏览器网页（RootWebArea 文档）内元素按“可聚焦/有默认动作”判定可交互，
  并把网页元素矩形裁剪到文档视口内；任务栏、桌面图标窗口的收集方式。
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

import uiautomation as auto
from uiautomation import uiautomation as _uia_module

from . import apps
from .types import Element, Rect

logger = logging.getLogger(__name__)

_PID = auto.PropertyId
_CT = auto.ControlType

_TREE_SCOPE_ELEMENT = 1
_TREE_SCOPE_CHILDREN = 2

# 缓存的属性：一次跨进程调用全部取回
_CACHED_PROPS = (
    _PID.NameProperty,
    _PID.ControlTypeProperty,
    _PID.BoundingRectangleProperty,
    _PID.IsEnabledProperty,
    _PID.IsOffscreenProperty,
    _PID.IsKeyboardFocusableProperty,
    _PID.IsPasswordProperty,
    _PID.HelpTextProperty,
    _PID.AutomationIdProperty,
    _PID.FrameworkIdProperty,
    _PID.ValueValueProperty,
    _PID.LegacyIAccessibleDefaultActionProperty,
    _PID.LegacyIAccessibleStateProperty,
)

# 原生界面里直接视为可交互的控件类型（参考 Windows-MCP tree/config.py，去掉了滚动条这类噪音）
_INTERACTIVE_TYPES = {
    _CT.ButtonControl,
    _CT.CheckBoxControl,
    _CT.ComboBoxControl,
    _CT.DataItemControl,
    _CT.EditControl,
    _CT.HeaderItemControl,
    _CT.HyperlinkControl,
    _CT.ListItemControl,
    _CT.MenuItemControl,
    _CT.RadioButtonControl,
    _CT.SliderControl,
    _CT.SpinnerControl,
    _CT.SplitButtonControl,
    _CT.TabItemControl,
    _CT.TreeItemControl,
}

# 网页里这些“非标准”控件（例如带 onclick + tabindex 的 div）在“可聚焦且有默认动作”时也算可交互。
# 注意默认动作文字是本地化的（中文系统上是「按」「跳转」「双击」等），所以只判断非空，不比对具体单词；
# 只有默认动作、不可聚焦的往往是整块容器（例如挂了点击事件的页面根节点），不收集。
_DOM_EXTRA_TYPES = {
    _CT.GroupControl,
    _CT.CustomControl,
    _CT.TextControl,
    _CT.ImageControl,
    _CT.PaneControl,
}

# 这些控件本身就是点击目标，内部子元素对点击没有意义，不再往下遍历，节省调用
_NO_DESCEND_TYPES = {
    _CT.ButtonControl,
    _CT.CheckBoxControl,
    _CT.ComboBoxControl,
    _CT.EditControl,
    _CT.HyperlinkControl,
    _CT.RadioButtonControl,
    _CT.SliderControl,
    _CT.SpinnerControl,
    _CT.ScrollBarControl,
    _CT.ProgressBarControl,
}

_VALUE_TYPES = {_CT.EditControl, _CT.ComboBoxControl}
_ROW_TYPES = {_CT.ListItemControl, _CT.DataItemControl}

_STATE_SYSTEM_READONLY = 0x40
_NAME_LIMIT = 60
_VALUE_LIMIT = 40

_TASKBAR_CLASSES = ("Shell_TrayWnd", "Shell_SecondaryTrayWnd")
_DESKTOP_CLASSES = ("Progman", "WorkerW")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.WindowFromPoint.argtypes = [wintypes.POINT]
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetAncestor.restype = wintypes.HWND
_user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowW.restype = wintypes.HWND
_user32.IsHungAppWindow.argtypes = [wintypes.HWND]
_GA_ROOT = 2


class _Timeout(Exception):
    pass


def _root_at(x: int, y: int) -> int:
    hwnd = _user32.WindowFromPoint(wintypes.POINT(x, y))
    return (_user32.GetAncestor(hwnd, _GA_ROOT) or 0) if hwnd else 0


def _rect_of(raw) -> Rect:
    return Rect(raw.left, raw.top, raw.right, raw.bottom)


def _str_prop(elem, pid: int) -> str:
    """读取缓存的字符串属性；不支持该属性时 UIA 返回一个哨兵对象，统一当空串处理。"""
    try:
        v = elem.GetCachedPropertyValue(pid)
    except Exception:
        return ""
    return v if isinstance(v, str) else ""


def _int_prop(elem, pid: int) -> int:
    try:
        v = elem.GetCachedPropertyValue(pid)
    except Exception:
        return 0
    return v if isinstance(v, int) else 0


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class _Collector:
    def __init__(self, region: Rect, max_count: int, deadline: float) -> None:
        client = _uia_module._AutomationClient.instance()
        self.uia = client.IUIAutomation
        self.region = region
        self.max_count = max_count
        self.deadline = deadline
        self.results: list[Element] = []

        # 子元素缓存请求：只缓存 Children 一层，父元素本身不重复取（参考 Windows-MCP cache_utils）
        self.children_req = self.uia.CreateCacheRequest()
        for pid in _CACHED_PROPS:
            self.children_req.AddProperty(pid)
        self.children_req.TreeScope = _TREE_SCOPE_CHILDREN
        # 根元素本身的缓存请求
        self.element_req = self.children_req.Clone()
        self.element_req.TreeScope = _TREE_SCOPE_ELEMENT

        # 当前正在遍历的窗口
        self.hwnd = 0
        self.title = ""
        self.accept_roots: set[int] = set()

    # ------------------------------------------------------------ 窗口级

    def collect_window(self, hwnd: int, title: str, accept_roots: set[int]) -> None:
        win_rect = apps.window_rect(hwnd)
        clip = win_rect.intersect(self.region)
        if clip.is_empty():
            return
        self.hwnd = hwnd
        self.title = title
        self.accept_roots = accept_roots
        root = self.uia.ElementFromHandleBuildCache(hwnd, self.element_req)
        if not root:
            return
        self._walk(root, clip, in_dom=False, depth=0, in_row=False)

    # ------------------------------------------------------------ 遍历

    def _children(self, elem) -> list:
        updated = elem.BuildUpdatedCache(self.children_req)
        arr = updated.GetCachedChildren()
        if not arr:
            return []
        return [arr.GetElement(i) for i in range(arr.Length)]

    def _walk(self, elem, clip: Rect, in_dom: bool, depth: int, in_row: bool) -> None:
        if time.perf_counter() > self.deadline:
            raise _Timeout
        if len(self.results) >= self.max_count or depth > 60:
            return

        ctype = elem.CachedControlType
        rect = _rect_of(elem.CachedBoundingRectangle)
        offscreen = bool(elem.CachedIsOffscreen)

        # 进入网页文档：之后的元素都裁剪到文档视口内（滚出视口的元素矩形仍可能落在窗口内）
        if ctype == _CT.DocumentControl and elem.CachedFrameworkId == "Chrome" and not in_dom:
            in_dom = True
            clip = clip.intersect(rect)
            if clip.is_empty():
                return

        if not rect.is_empty():
            visible = rect.intersect(clip)
            # 整块都在可见范围外：子树一并跳过（剪枝是性能的关键）
            if visible.is_empty():
                return
            if (
                not offscreen
                and elem.CachedIsEnabled
                and not (in_row and ctype == _CT.EditControl)
                and self._is_interactive(elem, ctype, in_dom)
            ):
                self._add(elem, ctype, visible)
        elif offscreen:
            # 空矩形又在屏幕外：折叠的菜单、隐藏的面板等
            return

        if ctype in _NO_DESCEND_TYPES:
            return
        try:
            children = self._children(elem)
        except Exception:
            return
        # 原生列表行（资源管理器详细信息视图等）里每一列都是一个只读 Edit，和整行重复，不单独收集
        row = not in_dom and ctype in _ROW_TYPES
        for child in children:
            try:
                self._walk(child, clip, in_dom, depth + 1, row)
            except _Timeout:
                raise
            except Exception:
                # 元素在遍历中消失、跨进程调用失败等：跳过这一个
                continue

    def _is_interactive(self, elem, ctype: int, in_dom: bool) -> bool:
        if ctype == _CT.DocumentControl:
            # 只要可编辑的文档（记事本、Word 正文等）；网页根文档是只读的
            if elem.CachedAutomationId == "RootWebArea":
                return False
            return not (_int_prop(elem, _PID.LegacyIAccessibleStateProperty) & _STATE_SYSTEM_READONLY)
        if not in_dom:
            return ctype in _INTERACTIVE_TYPES
        # 网页内：标准控件直接算；纯展示的 li / 表格单元格需可聚焦或有默认动作；
        # 其他普通元素（div、span、img 等）需同时可聚焦且有默认动作
        has_action = bool(_str_prop(elem, _PID.LegacyIAccessibleDefaultActionProperty))
        focusable = bool(elem.CachedIsKeyboardFocusable)
        if ctype in _INTERACTIVE_TYPES:
            if ctype == _CT.ListItemControl or ctype == _CT.DataItemControl:
                return has_action or focusable
            return True
        if ctype in _DOM_EXTRA_TYPES:
            return has_action and focusable
        return False

    def _add(self, elem, ctype: int, visible: Rect) -> None:
        cx, cy = visible.center
        if _root_at(cx, cy) not in self.accept_roots:
            return  # 中心点被别的窗口挡住
        name = (elem.CachedName or "").strip()
        if not name:
            name = (elem.CachedHelpText or "").strip() or self._child_text(elem) or (elem.CachedAutomationId or "").strip()
        value = ""
        if ctype in _VALUE_TYPES and not elem.CachedIsPassword:
            value = _truncate(_str_prop(elem, _PID.ValueValueProperty), _VALUE_LIMIT)
        type_name = auto.ControlTypeNames.get(ctype, "Control").removesuffix("Control")
        self.results.append(
            Element(
                name=_truncate(name, _NAME_LIMIT),
                control_type=type_name,
                rect=visible,
                window_title=self.title,
                hwnd=self.hwnd,
                value=value,
            )
        )

    def _child_text(self, elem) -> str:
        """名字为空时，取前几个子元素里的文字作为名字（例如只有图标+文字的按钮）。"""
        try:
            children = self._children(elem)
        except Exception:
            return ""
        for child in children[:5]:
            text = (child.CachedName or "").strip()
            if text:
                return text
        return ""


def _window_label(hwnd: int, cls: str) -> str:
    if cls in _TASKBAR_CLASSES:
        return "任务栏"
    if cls in _DESKTOP_CLASSES:
        return "桌面"
    return apps.window_title(hwnd) or cls


def _hit_roots(rect: Rect, steps: int = 8) -> set[int]:
    """在矩形内均匀采样，返回命中的根窗口集合，用来快速判断窗口有没有露出来的部分。"""
    roots: set[int] = set()
    for i in range(steps):
        for j in range(steps):
            x = rect.left + (2 * i + 1) * rect.width // (2 * steps)
            y = rect.top + (2 * j + 1) * rect.height // (2 * steps)
            roots.add(_root_at(x, y))
    return roots


def _ordered_windows(region: Rect) -> list[tuple[int, str, set[int]]]:
    """按优先级返回要遍历的窗口：(句柄, 显示名, 遮挡判定时接受的根窗口集合)。

    顺序：前台窗口 > 其他可见窗口（Z 序） > 任务栏 > 桌面图标。
    """
    fg = apps.foreground_window()
    fg_ok = False
    normal: list[int] = []
    taskbars: list[int] = []
    for hwnd in apps.enum_top_windows():
        if not apps.is_visible(hwnd) or apps.is_minimized(hwnd) or apps.is_cloaked(hwnd):
            continue
        # 无响应的窗口：UIA 调用会一直卡到超时，直接跳过
        if _user32.IsHungAppWindow(hwnd):
            continue
        cls = apps.window_class(hwnd)
        if cls in _DESKTOP_CLASSES:
            continue
        rect = apps.window_rect(hwnd).intersect(region)
        if rect.is_empty():
            continue
        if cls in _TASKBAR_CLASSES:
            taskbars.append(hwnd)
        elif hwnd == fg:
            fg_ok = True
        else:
            normal.append(hwnd)

    ordered: list[tuple[int, str, set[int]]] = []
    if fg_ok:
        ordered.append((fg, _window_label(fg, apps.window_class(fg)), {fg}))
    for hwnd in normal:
        # 完全被挡住的窗口直接跳过，省掉整棵 UI 树的遍历
        if hwnd in _hit_roots(apps.window_rect(hwnd).intersect(region)):
            ordered.append((hwnd, _window_label(hwnd, apps.window_class(hwnd)), {hwnd}))
    for hwnd in taskbars:
        ordered.append((hwnd, "任务栏", {hwnd}))

    # 桌面图标：Progman 下的 SysListView32；Win11 新版本里命中测试可能落在 WorkerW 上，一并接受
    progman = _user32.FindWindowW("Progman", None)
    if progman:
        desktop_roots = {progman}
        for hwnd in apps.enum_top_windows():
            if apps.window_class(hwnd) == "WorkerW":
                desktop_roots.add(hwnd)
        if _hit_roots(region) & desktop_roots:
            ordered.append((progman, "桌面", desktop_roots))
    return ordered


def collect_elements(region: Rect, max_count: int = 120, timeout: float = 3.0) -> list[Element]:
    """收集 region（物理像素、虚拟桌面坐标）内可见且可交互的元素。

    超时或达到 max_count 时直接返回已收集的部分；优先级为前台窗口 > 其他窗口 > 任务栏 > 桌面。
    """
    deadline = time.perf_counter() + timeout
    collector = _Collector(region, max_count, deadline)
    for hwnd, label, roots in _ordered_windows(region):
        if len(collector.results) >= max_count:
            break
        try:
            collector.collect_window(hwnd, label, roots)
        except _Timeout:
            logger.debug("collect_elements 超时，已收集 %d 个元素", len(collector.results))
            break
        except Exception as e:  # 窗口已关闭、进程无响应等
            logger.debug("遍历窗口 %s 失败：%s", hwnd, e)
            continue
    return collector.results[:max_count]
