"""鼠标键盘模拟（SendInput）。坐标均为物理像素，必须在 DesktopWorker 线程中调用。"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0001, 0x0002, 0x0004
WHEEL_DELTA = 120

_BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise OSError(
            "输入被系统拦截（目标窗口可能以管理员权限运行，或处于锁屏/安全桌面），"
            f"错误码 {ctypes.get_last_error()}"
        )


def _mouse(flags: int, data: int = 0) -> INPUT:
    return INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, 0)))


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))


# ---------------- 鼠标 ----------------


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def move(x: int, y: int) -> tuple[int, int]:
    """移动鼠标并返回实际落点。"""
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.02)
    return cursor_pos()


def click(x: int, y: int, button: str = "left", clicks: int = 1) -> tuple[int, int]:
    down, up = _BUTTONS[button]
    pos = move(x, y)
    time.sleep(0.03)
    for i in range(clicks):
        _send(_mouse(down), _mouse(up))
        if i + 1 < clicks:
            time.sleep(0.06)
    return pos


def scroll(x: int, y: int, direction: str, amount: int) -> None:
    move(x, y)
    if direction in ("up", "down"):
        delta = WHEEL_DELTA if direction == "up" else -WHEEL_DELTA
        flag = MOUSEEVENTF_WHEEL
    else:
        delta = WHEEL_DELTA if direction == "right" else -WHEEL_DELTA
        flag = MOUSEEVENTF_HWHEEL
    for _ in range(amount):
        _send(_mouse(flag, delta))
        time.sleep(0.03)


def drag(x1: int, y1: int, x2: int, y2: int, button: str = "left", steps: int = 15) -> None:
    down, up = _BUTTONS[button]
    move(x1, y1)
    _send(_mouse(down))
    time.sleep(0.05)
    try:
        for i in range(1, steps + 1):
            user32.SetCursorPos(x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps)
            time.sleep(0.015)
        time.sleep(0.05)
    finally:
        _send(_mouse(up))


# ---------------- 键盘 ----------------

_VK_NAMES = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "windows": 0x5B,
    "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "capslock": 0x14, "printscreen": 0x2C, "menu": 0x5D, "apps": 0x5D,
}
_VK_NAMES.update({f"f{i}": 0x6F + i for i in range(1, 13)})
# 需要扩展键标志的虚拟键，否则方向键等可能被当作小键盘按键
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5D}
MODIFIERS = {"ctrl", "control", "shift", "alt", "win", "windows"}


def key_to_vk(name: str) -> int:
    name = name.strip().lower()
    if name in _VK_NAMES:
        return _VK_NAMES[name]
    if len(name) == 1:
        if name.isalnum() and name.isascii():
            return ord(name.upper())
        res = user32.VkKeyScanW(ord(name))
        if res != -1:
            return res & 0xFF
    raise ValueError(f"无法识别的按键：{name}")


def _vk_input(vk: int, up: bool) -> INPUT:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0)
    return _key(vk=vk, flags=flags)


def hotkey(keys: list[str]) -> None:
    """按顺序按下所有键，再逆序松开。"""
    vks = [key_to_vk(k) for k in keys]
    try:
        for vk in vks:
            _send(_vk_input(vk, False))
            time.sleep(0.02)
    finally:
        for vk in reversed(vks):
            _send(_vk_input(vk, True))
            time.sleep(0.01)


def type_unicode(text: str) -> None:
    """逐字符发送 Unicode 输入，不经过输入法，也不占用剪贴板。"""
    for ch in text.replace("\r\n", "\n"):
        if ch == "\n":
            _send(_vk_input(0x0D, False), _vk_input(0x0D, True))
        elif ch == "\t":
            _send(_vk_input(0x09, False), _vk_input(0x09, True))
        else:
            data = ch.encode("utf-16-le")
            for i in range(0, len(data), 2):  # 补充平面字符拆成两个 UTF-16 码元
                unit = int.from_bytes(data[i : i + 2], "little")
                _send(
                    _key(scan=unit, flags=KEYEVENTF_UNICODE),
                    _key(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
                )
        time.sleep(0.004)


# ---------------- 剪贴板 ----------------

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
user32.OpenClipboard.argtypes = (wintypes.HWND,)
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
kernel32.GlobalFree.argtypes = (wintypes.HGLOBAL,)


def _open_clipboard() -> None:
    for _ in range(10):
        if user32.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise OSError("剪贴板被其他程序占用")


def get_clipboard_text() -> str | None:
    _open_clipboard()
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> None:
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    ptr = kernel32.GlobalLock(handle)
    ctypes.memmove(ptr, data, size)
    kernel32.GlobalUnlock(handle)
    _open_clipboard()
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise OSError("写入剪贴板失败")
    finally:
        user32.CloseClipboard()


def type_paste(text: str) -> None:
    """通过剪贴板粘贴输入，完成后恢复原剪贴板文本。"""
    previous = get_clipboard_text()
    set_clipboard_text(text)
    hotkey(["ctrl", "v"])
    time.sleep(0.15)  # 等目标程序读完剪贴板再恢复
    if previous is not None:
        set_clipboard_text(previous)
