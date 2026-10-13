"""桌面会话：串联截图、元素编号、坐标换算与键鼠动作。

所有公开方法都是同步的，必须通过 DesktopWorker 在专用线程中调用。本模块不依赖 AstrBot。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from PIL import Image

from . import annotate, apps, capture, elements, input
from .coords import NORMALIZED, Frame, describe_mode, fit_size
from .types import Element

MAX_ZOOM_UPSCALE = 3.0
MIN_ZOOM_SIZE = 8  # 放大区域的最小边长（物理像素）

_KEY_ALIASES = {"control": "ctrl", "windows": "win", "del": "delete", "escape": "esc", "return": "enter"}


def normalize_combo(combo: str) -> frozenset[str]:
    parts = [p.strip().lower() for p in combo.replace(" ", "").split("+") if p.strip()]
    return frozenset(_KEY_ALIASES.get(p, p) for p in parts)


@dataclass
class PilotConfig:
    coord_mode: str = NORMALIZED
    max_long_edge: int = 1280
    image_format: str = "jpeg"
    jpeg_quality: int = 80
    annotate: bool = True
    max_elements: int = 120
    element_timeout: float = 3.0
    default_display: int = 0
    type_method: str = "unicode"
    screenshot_after_action: bool = False
    action_delay: float = 0.6
    blocked_hotkeys: list[str] = field(default_factory=lambda: ["win+l", "ctrl+alt+delete"])


@dataclass
class ToolOutput:
    text: str
    image_b64: str | None = None
    mime: str = "image/jpeg"


class DesktopSession:
    def __init__(self, config: PilotConfig) -> None:
        self.cfg = config
        self._frame: Frame | None = None
        self._frame_seq = 0
        self._elements: list[Element] = []
        self._elements_frame_id = 0
        self._blocked = {normalize_combo(c) for c in config.blocked_hotkeys if c.strip()}

    # ---------------- 观察 ----------------

    def screenshot(self, display: int | None = None, annotate_elements: bool | None = None,
                   wait_seconds: float = 0) -> ToolOutput:
        if wait_seconds > 0:
            time.sleep(min(wait_seconds, 10))
        region, region_desc = capture.pick_display(self.cfg.default_display if display is None else display)
        raw = capture.grab(region)

        notes: list[str] = []
        found: list[Element] = []
        if self.cfg.annotate if annotate_elements is None else annotate_elements:
            try:
                found = elements.collect_elements(region, self.cfg.max_elements, self.cfg.element_timeout)
            except Exception as e:  # 元素采集失败不影响截图本身
                notes.append(f"读取界面元素失败（{e}），本次只能用坐标操作")

        frame = self._new_frame(region, raw, "screenshot")
        image = raw.resize((frame.image_width, frame.image_height), Image.LANCZOS)
        annotate.draw_elements(image, frame, list(enumerate(found, start=1)))
        cursor = input.cursor_pos()
        annotate.draw_cursor(image, frame, *cursor)
        self._elements, self._elements_frame_id = found, frame.frame_id

        lines = [
            f"截图#{frame.frame_id}：{region_desc}，屏幕区域 {region.width}x{region.height}，"
            f"图片 {frame.image_width}x{frame.image_height}",
            f"坐标规则：{describe_mode(self.cfg.coord_mode, frame)}。之后的坐标参数都以这张图为准。",
            f"鼠标位置：{self._describe_point(*cursor)}（图上红色十字）",
            f"前台窗口：{self._foreground_title()}",
            *notes,
        ]
        if found:
            lines.append(f"可交互元素共 {len(found)} 个，操作时优先用编号 label（比坐标更准）：")
            lines.extend(self._format_elements(found))
        elif self.cfg.annotate:
            lines.append("没有识别到可交互元素（可能是游戏、画布或远程桌面），请用坐标操作，必要时用 desktop_zoom 放大确认。")
        return self._with_image(image, "\n".join(lines))

    def zoom(self, x1: float, y1: float, x2: float, y2: float) -> ToolOutput:
        frame = self._require_frame()
        region = frame.sub_region(x1, y1, x2, y2, self.cfg.coord_mode)
        if region.width < MIN_ZOOM_SIZE or region.height < MIN_ZOOM_SIZE:
            raise ValueError("放大区域太小了，请框选更大一点的范围")
        raw = capture.grab(region)
        new = self._new_frame(region, raw, "zoom", MAX_ZOOM_UPSCALE)
        image = raw.resize((new.image_width, new.image_height), Image.LANCZOS)
        # 保留原编号，方便模型在放大图里继续按编号操作
        inside = [(i, el) for i, el in enumerate(self._elements, start=1)
                  if not el.rect.intersect(region).is_empty()]
        annotate.draw_elements(image, new, inside)
        annotate.draw_cursor(image, new, *input.cursor_pos())
        factor = new.image_width / region.width
        text = (
            f"放大图#{new.frame_id}：屏幕区域 ({region.left},{region.top})-({region.right},{region.bottom})，"
            f"图片 {new.image_width}x{new.image_height}（相当于 {factor:.2f} 倍物理像素）。\n"
            f"坐标规则：{describe_mode(self.cfg.coord_mode, new)}。之后的坐标参数改为以这张放大图为准，"
            "编号不变；重新截图后恢复以整屏为准。"
        )
        return self._with_image(image, text)

    # ---------------- 动作 ----------------

    def click(self, label: int | None, x: float | None, y: float | None,
              button: str = "left", clicks: int = 1) -> ToolOutput:
        if button not in ("left", "right", "middle"):
            raise ValueError("button 只能是 left、right 或 middle")
        clicks = max(0, min(int(clicks), 3))
        sx, sy, target = self._resolve(label, x, y)
        if clicks == 0:
            pos = input.move(sx, sy)
            action = "鼠标已移动到"
        else:
            pos = input.click(sx, sy, button, clicks)
            action = f"已{_BUTTON_NAMES[button]}{_CLICK_NAMES.get(clicks, f'{clicks}连击')}"
        return self._after_action(f"{action} {target}，鼠标实际位置 {self._describe_point(*pos)}")

    def type_text(self, text: str, label: int | None, x: float | None, y: float | None,
                  clear: bool = False, press_enter: bool = False) -> ToolOutput:
        parts = []
        if label is not None or x is not None:
            sx, sy, target = self._resolve(label, x, y)
            input.click(sx, sy)
            time.sleep(0.15)
            parts.append(f"已点击 {target}")
        if clear:
            input.hotkey(["ctrl", "a"])
            input.hotkey(["delete"])
        if text:
            if self.cfg.type_method == "paste":
                input.type_paste(text)
            else:
                input.type_unicode(text)
        if press_enter:
            input.hotkey(["enter"])
        parts.append(f"已输入 {len(text)} 个字符" + ("（先清空了原内容）" if clear else "")
                     + ("并按下回车" if press_enter else ""))
        return self._after_action("，".join(parts))

    def scroll(self, direction: str, amount: int, label: int | None, x: float | None,
               y: float | None) -> ToolOutput:
        if direction not in ("up", "down", "left", "right"):
            raise ValueError("direction 只能是 up、down、left 或 right")
        amount = max(1, min(int(amount), 30))
        if label is None and x is None:
            sx, sy = input.cursor_pos()
            target = "当前鼠标位置"
        else:
            sx, sy, target = self._resolve(label, x, y)
        input.scroll(sx, sy, direction, amount)
        return self._after_action(f"已在 {target} 向 {direction} 滚动 {amount} 格")

    def drag(self, x1: float, y1: float, x2: float, y2: float) -> ToolOutput:
        frame = self._require_frame()
        mode = self.cfg.coord_mode
        a = frame.to_screen(x1, y1, mode)
        b = frame.to_screen(x2, y2, mode)
        input.drag(*a, *b)
        return self._after_action(f"已从 ({x1:g},{y1:g}) 拖拽到 ({x2:g},{y2:g})")

    def hotkey(self, combo: str) -> ToolOutput:
        keys = [k for k in combo.replace(" ", "").split("+") if k]
        if not keys:
            raise ValueError("请提供按键，例如 ctrl+c")
        if normalize_combo(combo) in self._blocked:
            raise PermissionError(f"组合键 {combo} 已被管理员禁用")
        input.hotkey(keys)
        return self._after_action(f"已按下 {combo}")

    def app(self, action: str, name: str) -> ToolOutput:
        if action == "list":
            wins = apps.list_windows()
            if not wins:
                return ToolOutput("当前没有可见窗口")
            rows = [f"- {'[前台] ' if w.is_foreground else ''}{'[最小化] ' if w.is_minimized else ''}"
                    f"{w.title}（{w.process_name}）" for w in wins]
            return ToolOutput("当前窗口：\n" + "\n".join(rows))
        if not name.strip():
            raise ValueError("请提供应用或窗口名称")
        if action == "switch":
            win = apps.switch_window(name)
            if not win.is_foreground:
                raise RuntimeError(f"找到了窗口「{win.title}」，但系统拒绝把它切到前台，可以尝试点击任务栏上的图标")
            return self._after_action(f"已切换到窗口「{win.title}」")
        if action == "launch":
            launched = apps.launch_app(name)
            return self._after_action(f"已启动「{launched}」，应用可能需要几秒加载，可以用 wait_seconds 参数等待后再截图",
                                      delay=max(self.cfg.action_delay, 2.0))
        raise ValueError("action 只能是 list、switch 或 launch")

    # ---------------- 内部 ----------------

    def _new_frame(self, region, raw: Image.Image, kind: str, max_upscale: float = 1.0) -> Frame:
        self._frame_seq += 1
        w, h = fit_size(raw.width, raw.height, self.cfg.max_long_edge, max_upscale)
        self._frame = Frame(self._frame_seq, region, w, h, kind)
        return self._frame

    def _require_frame(self) -> Frame:
        if self._frame is None:
            raise RuntimeError("还没有截图，请先调用 desktop_screenshot 观察屏幕")
        return self._frame

    def _resolve(self, label: int | None, x: float | None, y: float | None) -> tuple[int, int, str]:
        if label is not None:
            if not self._elements:
                raise ValueError("当前没有可用的元素编号，请先调用 desktop_screenshot")
            if not 1 <= int(label) <= len(self._elements):
                raise ValueError(f"编号 {label} 不存在，有效范围是 1~{len(self._elements)}")
            el = self._elements[int(label) - 1]
            sx, sy = el.rect.center
            return sx, sy, f"[{label}] {el.control_type}「{el.name}」"
        if x is None or y is None:
            raise ValueError("请提供元素编号 label，或者同时提供坐标 x 和 y")
        frame = self._require_frame()
        sx, sy = frame.to_screen(x, y, self.cfg.coord_mode)
        return sx, sy, f"坐标 ({x:g},{y:g})"

    def _describe_point(self, sx: int, sy: int) -> str:
        frame = self._frame
        if frame is None or not frame.region.contains(sx, sy):
            return f"屏幕物理坐标 ({sx},{sy})，不在当前图片范围内"
        mx, my = frame.from_screen(sx, sy, self.cfg.coord_mode)
        return f"({mx},{my})"

    def _format_elements(self, found: list[Element]) -> list[str]:
        frame = self._frame
        lines, current = [], None
        for i, el in enumerate(found, start=1):
            if el.window_title != current:
                current = el.window_title
                lines.append(f"· 窗口「{current or '桌面'}」")
            cx, cy = frame.from_screen(*el.rect.center, self.cfg.coord_mode)
            value = f" 值=「{el.value}」" if el.value else ""
            lines.append(f"  [{i}] {el.control_type}「{el.name}」{value} @({cx},{cy})")
        return lines

    @staticmethod
    def _foreground_title() -> str:
        hwnd = apps.foreground_window()
        if not hwnd:
            return "无"
        return f"{apps.window_title(hwnd) or apps.window_class(hwnd)}（{apps.process_name(hwnd)}）"

    def _with_image(self, image: Image.Image, text: str) -> ToolOutput:
        data, mime = capture.encode(image, self.cfg.image_format, self.cfg.jpeg_quality)
        return ToolOutput(text, data, mime)

    def _after_action(self, text: str, delay: float | None = None) -> ToolOutput:
        if self._elements:
            text += "。界面可能已变化，旧编号仅在界面未变时有效"
        if not self.cfg.screenshot_after_action:
            return ToolOutput(text + "。需要确认结果时请调用 desktop_screenshot")
        time.sleep(self.cfg.action_delay if delay is None else delay)
        shot = self.screenshot()
        return ToolOutput(f"{text}。\n\n以下是动作后的新截图：\n{shot.text}", shot.image_b64, shot.mime)


_BUTTON_NAMES = {"left": "左键", "right": "右键", "middle": "中键"}
_CLICK_NAMES = {1: "单击", 2: "双击", 3: "三击"}
