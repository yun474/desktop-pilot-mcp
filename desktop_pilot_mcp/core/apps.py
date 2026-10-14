"""窗口列举、窗口切换与应用启动。

所有函数都在 DesktopWorker 的单线程中同步调用（线程级 PerMonitorV2 DPI 感知），
因此这里取到的窗口矩形都是物理像素、虚拟桌面坐标。

部分思路参考 Windows-MCP 0.8.1（MIT License, https://github.com/CursorTouch/Windows-MCP）：
- desktop/service.py `bring_window_to_top`：AttachThreadInput 到前台线程与目标线程后再 SetForegroundWindow；
- desktop/service.py `get_apps_from_start_menu` / `launch_app`：Get-StartApps + shell:AppsFolder\\<AppID> 启动。
"""

from __future__ import annotations

import ctypes
import difflib
import json
import os
import subprocess
import time
from ctypes import wintypes

from .types import Rect, WindowInfo

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_dwmapi = ctypes.WinDLL("dwmapi")

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetAncestor.restype = wintypes.HWND
_user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetWindow.restype = wintypes.HWND
_user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.BringWindowToTop.argtypes = [wintypes.HWND]
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowExW.restype = wintypes.HWND
_user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
_user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_APPWINDOW = 0x00040000
_WS_EX_NOACTIVATE = 0x08000000
_GW_OWNER = 4
_GA_ROOT = 2
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_DWMWA_CLOAKED = 14
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SW_RESTORE = 9
_VK_MENU = 0x12
_KEYEVENTF_KEYUP = 0x0002
_ASFW_ANY = 0xFFFFFFFF
_CREATE_NO_WINDOW = 0x08000000

# 这些类名的顶层窗口不是用户意义上的“应用窗口”
_EXCLUDED_CLASSES = {
    "Progman",
    "WorkerW",
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "Windows.UI.Core.CoreWindow",
    "Windows.UI.Composition.DesktopWindowContentBridge",
    "XamlExplorerHostIslandWindow",
}

_START_APPS_TTL = 600.0
_start_apps_cache: tuple[float, list[tuple[str, str]]] | None = None


# ---------------------------------------------------------------- 底层窗口工具（elements.py 也会用到）


def enum_top_windows() -> list[int]:
    """按 Z 序（从上到下）返回所有顶层窗口句柄。"""
    handles: list[int] = []

    def _cb(hwnd, _lparam):
        handles.append(hwnd)
        return True

    _user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    return handles


def window_title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def is_cloaked(hwnd: int) -> bool:
    """被 DWM 隐藏的窗口（其他虚拟桌面、挂起的 UWP 等）虽然 IsWindowVisible 为真，但实际看不见。"""
    cloaked = wintypes.DWORD(0)
    hr = _dwmapi.DwmGetWindowAttribute(hwnd, _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return hr == 0 and cloaked.value != 0


def window_rect(hwnd: int) -> Rect:
    """优先取 DWM 的可见边框（不含 Win10/11 透明的缩放边框），失败再退回 GetWindowRect。"""
    rc = wintypes.RECT()
    hr = _dwmapi.DwmGetWindowAttribute(
        hwnd, _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rc), ctypes.sizeof(rc)
    )
    if hr != 0:
        _user32.GetWindowRect(hwnd, ctypes.byref(rc))
    return Rect(rc.left, rc.top, rc.right, rc.bottom)


def root_window(hwnd: int) -> int:
    return _user32.GetAncestor(hwnd, _GA_ROOT) or 0


def foreground_window() -> int:
    hwnd = _user32.GetForegroundWindow()
    return root_window(hwnd) if hwnd else 0


def is_minimized(hwnd: int) -> bool:
    return bool(_user32.IsIconic(hwnd))


def is_visible(hwnd: int) -> bool:
    return bool(_user32.IsWindowVisible(hwnd))


def ex_style(hwnd: int) -> int:
    return _user32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _process_name_by_pid(pid: int) -> str:
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        _kernel32.CloseHandle(handle)


def process_name(hwnd: int) -> str:
    """窗口所属进程的可执行文件名。UWP 应用的外框属于 ApplicationFrameHost，取内部 CoreWindow 的进程。"""
    if window_class(hwnd) == "ApplicationFrameWindow":
        core = _user32.FindWindowExW(hwnd, None, "Windows.UI.Core.CoreWindow", None)
        if core:
            name = _process_name_by_pid(window_pid(core))
            if name:
                return name
    return _process_name_by_pid(window_pid(hwnd))


def _is_app_window(hwnd: int) -> bool:
    """与 Alt+Tab 的判定基本一致：可见、有标题、非工具窗口、未被 DWM 隐藏。"""
    if not _user32.IsWindowVisible(hwnd):
        return False
    if not window_title(hwnd).strip():
        return False
    style = ex_style(hwnd)
    if style & _WS_EX_APPWINDOW == 0:
        if style & (_WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE):
            return False
        # 有所有者的窗口（对话框等）一般不单独出现在 Alt+Tab 里，但仍然是用户能看到并操作的窗口，保留
    if window_class(hwnd) in _EXCLUDED_CLASSES:
        return False
    if is_cloaked(hwnd):
        return False
    if not is_minimized(hwnd) and window_rect(hwnd).is_empty():
        return False
    return True


def _make_info(hwnd: int, fg: int) -> WindowInfo:
    return WindowInfo(
        hwnd=hwnd,
        title=window_title(hwnd),
        process_name=process_name(hwnd),
        rect=window_rect(hwnd),
        is_foreground=hwnd == fg,
        is_minimized=is_minimized(hwnd),
    )


# ---------------------------------------------------------------- 对外接口


def list_windows() -> list[WindowInfo]:
    """按 Z 序返回用户可见的应用窗口。"""
    fg = foreground_window()
    result: list[WindowInfo] = []
    for hwnd in enum_top_windows():
        try:
            if _is_app_window(hwnd):
                result.append(_make_info(hwnd, fg))
        except OSError:
            continue
    return result


def _match_window(name: str, windows: list[WindowInfo]) -> WindowInfo | None:
    key = name.strip().lower()
    if not key:
        return None

    def proc(w: WindowInfo) -> str:
        return w.process_name.lower().removesuffix(".exe")

    # 1. 标题完全一致  2. 进程名完全一致  3. 标题子串  4. 进程名子串；同级按 Z 序取最上面的
    for pred in (
        lambda w: w.title.lower() == key,
        lambda w: proc(w) == key.removesuffix(".exe"),
        lambda w: key in w.title.lower(),
        lambda w: key in proc(w),
    ):
        for w in windows:
            if pred(w):
                return w

    # 5. difflib 模糊兜底
    best, best_score = None, 0.0
    for w in windows:
        score = max(
            difflib.SequenceMatcher(None, key, w.title.lower()).ratio(),
            difflib.SequenceMatcher(None, key, proc(w)).ratio(),
        )
        if score > best_score:
            best, best_score = w, score
    return best if best_score >= 0.6 else None


def _bring_to_front(hwnd: int) -> bool:
    if is_minimized(hwnd):
        _user32.ShowWindow(hwnd, _SW_RESTORE)

    def ok() -> bool:
        return foreground_window() == hwnd

    if _user32.SetForegroundWindow(hwnd) and ok():
        return True

    # 前台锁：把本线程挂到前台线程和目标线程的输入队列上，借用它们的前台权限
    _user32.AllowSetForegroundWindow(_ASFW_ANY)
    cur_tid = _kernel32.GetCurrentThreadId()
    fg_hwnd = _user32.GetForegroundWindow()
    fg_tid = _user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
    target_tid = _user32.GetWindowThreadProcessId(hwnd, None)
    attached = []
    try:
        for tid in (fg_tid, target_tid):
            if tid and tid != cur_tid and tid not in attached:
                if _user32.AttachThreadInput(cur_tid, tid, True):
                    attached.append(tid)
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
    finally:
        for tid in attached:
            _user32.AttachThreadInput(cur_tid, tid, False)
    if ok():
        return True

    # 兜底：模拟一次 Alt 键，让系统认为本进程刚产生过输入，从而解除前台锁
    _user32.keybd_event(_VK_MENU, 0, 0, 0)
    _user32.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, 0)
    _user32.SetForegroundWindow(hwnd)
    return ok()


def switch_window(name: str) -> WindowInfo:
    """按标题/进程名模糊匹配窗口并切到前台。

    找不到时抛 LookupError；切换失败不抛异常，返回值的 is_foreground 为 False，由调用方提示。
    """
    windows = list_windows()
    target = _match_window(name, windows)
    if target is None:
        candidates = "；".join(f"{w.title}（{w.process_name}）" for w in windows[:20]) or "无"
        raise LookupError(f"没有找到与「{name}」匹配的窗口。当前窗口：{candidates}")

    hwnd = target.hwnd
    _bring_to_front(hwnd)
    # 还原/激活动画需要一点时间，等前台状态稳定后再取最新的窗口信息
    deadline = time.monotonic() + 0.5
    while foreground_window() != hwnd and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.1)
    return _make_info(hwnd, foreground_window())


# ---------------------------------------------------------------- 调整窗口

_SW_MAXIMIZE = 3
_SW_MINIMIZE = 6
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_user32.IsZoomed.argtypes = [wintypes.HWND]
_user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]


def find_window(name: str) -> WindowInfo:
    """按名称匹配窗口；名称为空时取前台窗口。"""
    windows = list_windows()
    if not name.strip():
        for w in windows:
            if w.is_foreground:
                return w
        raise LookupError("当前没有前台窗口，请提供窗口名称")
    target = _match_window(name, windows)
    if target is None:
        candidates = "；".join(f"{w.title}（{w.process_name}）" for w in windows[:20]) or "无"
        raise LookupError(f"没有找到与「{name}」匹配的窗口。当前窗口：{candidates}")
    return target


def set_window_state(hwnd: int, state: str) -> None:
    cmd = {"maximize": _SW_MAXIMIZE, "minimize": _SW_MINIMIZE, "restore": _SW_RESTORE}[state]
    _user32.ShowWindow(hwnd, cmd)


def move_window(hwnd: int, target: Rect) -> Rect:
    """把窗口的可见边框移动到 target（物理像素），返回调整后的实际可见区域。"""
    if is_minimized(hwnd) or _user32.IsZoomed(hwnd):
        _user32.ShowWindow(hwnd, _SW_RESTORE)
        time.sleep(0.15)
    # Win10/11 窗口四周有透明的缩放边框，SetWindowPos 设置的是含边框的外框，需要补上差值
    outer = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(outer))
    visible = window_rect(hwnd)
    dl, dt = visible.left - outer.left, visible.top - outer.top
    dr, db = outer.right - visible.right, outer.bottom - visible.bottom
    _user32.SetWindowPos(hwnd, None, target.left - dl, target.top - dt,
                         target.width + dl + dr, target.height + dt + db,
                         _SWP_NOZORDER | _SWP_NOACTIVATE)
    time.sleep(0.1)
    return window_rect(hwnd)


# ---------------------------------------------------------------- 启动应用


def _load_start_apps() -> list[tuple[str, str]]:
    """读取开始菜单应用列表 [(名称, AppID)]，缓存 10 分钟。"""
    global _start_apps_cache
    now = time.monotonic()
    if _start_apps_cache and now - _start_apps_cache[0] < _START_APPS_TTL:
        return _start_apps_cache[1]

    script = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
    )
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        timeout=30,
        creationflags=_CREATE_NO_WINDOW,
    )
    text = proc.stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0 or not text:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"获取开始菜单应用列表失败：{err or '无输出'}")
    data = json.loads(text)
    if isinstance(data, dict):  # 只有一个应用时 ConvertTo-Json 输出的是对象而不是数组
        data = [data]
    apps = [(d["Name"], d["AppID"]) for d in data if d.get("Name") and d.get("AppID")]
    _start_apps_cache = (now, apps)
    return apps


def _match_app(name: str, apps: list[tuple[str, str]]) -> tuple[str, str] | None:
    key = name.strip().lower()
    if not key:
        return None
    for app in apps:
        if app[0].lower() == key:
            return app
    # 名称子串：取名字最短的（“记事本”优先于“记事本（旧版）”这类）
    hits = [a for a in apps if key in a[0].lower()]
    if hits:
        return min(hits, key=lambda a: len(a[0]))
    # AppID 子串：方便用英文名找本地化名称的应用，例如 notepad -> Microsoft.WindowsNotepad_xxx!App
    compact = key.replace(" ", "")
    hits = [a for a in apps if compact in a[1].lower()]
    if hits:
        return min(hits, key=lambda a: len(a[1]))
    close = difflib.get_close_matches(key, [a[0].lower() for a in apps], n=1, cutoff=0.6)
    if close:
        return next(a for a in apps if a[0].lower() == close[0])
    return None


def launch_app(name: str) -> str:
    """从开始菜单应用列表中模糊匹配并启动应用，返回实际启动的应用名。"""
    apps = _load_start_apps()
    app = _match_app(name, apps)
    if app is None:
        names = [a[0] for a in apps]
        close = difflib.get_close_matches(name.strip(), names, n=5, cutoff=0.3)
        hint = "、".join(close) if close else "无"
        raise LookupError(f"开始菜单里没有找到「{name}」。最接近的应用：{hint}")
    app_name, app_id = app
    if os.path.isabs(app_id) and os.path.isfile(app_id):
        # 部分传统桌面应用的 AppID 就是 exe 完整路径（例如 D:\\xx\\Weixin.exe），直接 ShellExecute，工作目录设为程序所在目录
        os.startfile(app_id, cwd=os.path.dirname(app_id))
        return app_name
    # explorer 会立即返回（退出码恒为 1），不用等待
    subprocess.Popen(
        ["explorer.exe", f"shell:AppsFolder\\{app_id}"],
        creationflags=_CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return app_name
