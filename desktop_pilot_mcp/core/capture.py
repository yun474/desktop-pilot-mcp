"""屏幕截图与图片编码。必须在 DesktopWorker 线程中调用（依赖线程级 DPI 感知拿到物理像素）。"""

from __future__ import annotations

import base64
import ctypes
import io
from ctypes import wintypes

import mss
from PIL import Image

from .types import Rect

_MSS = getattr(mss, "MSS", None) or mss.mss


def monitors() -> list[Rect]:
    """所有显示器区域，下标 0 对应“显示器 1”。"""
    with _MSS() as sct:
        return [
            Rect(m["left"], m["top"], m["left"] + m["width"], m["top"] + m["height"])
            for m in sct.monitors[1:]
        ]


def virtual_screen() -> Rect:
    with _MSS() as sct:
        m = sct.monitors[0]
        return Rect(m["left"], m["top"], m["left"] + m["width"], m["top"] + m["height"])


def foreground_rect() -> Rect | None:
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return None
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return Rect(rect.left, rect.top, rect.right, rect.bottom)


def pick_display(display: int) -> tuple[Rect, str]:
    """根据显示器编号选区域。0 表示前台窗口所在显示器，-1 表示全部显示器。"""
    mons = monitors()
    if len(mons) == 1 and display in (-1, 0, 1):
        return mons[0], "显示器 1/1"
    if display == -1:
        return virtual_screen(), f"全部 {len(mons)} 个显示器"
    if display == 0:
        fg = foreground_rect()
        index = 0
        if fg is not None:
            areas = [_area(fg.intersect(m)) for m in mons]
            index = max(range(len(mons)), key=areas.__getitem__)
        return mons[index], f"显示器 {index + 1}/{len(mons)}（前台窗口所在）"
    if not 1 <= display <= len(mons):
        raise ValueError(f"显示器编号 {display} 不存在，当前共有 {len(mons)} 个显示器")
    return mons[display - 1], f"显示器 {display}/{len(mons)}"


def _area(r: Rect) -> int:
    return 0 if r.is_empty() else r.width * r.height


def grab(region: Rect) -> Image.Image:
    with _MSS() as sct:
        shot = sct.grab(
            {"left": region.left, "top": region.top, "width": region.width, "height": region.height}
        )
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def encode(image: Image.Image, fmt: str, quality: int) -> tuple[str, str]:
    """返回 (base64 数据, MIME 类型)。"""
    buf = io.BytesIO()
    if fmt == "png":
        image.save(buf, format="PNG", optimize=False)
        mime = "image/png"
    else:
        image.save(buf, format="JPEG", quality=quality)
        mime = "image/jpeg"
    return base64.b64encode(buf.getvalue()).decode("ascii"), mime
