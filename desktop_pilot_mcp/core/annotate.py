"""在缩放后的截图上绘制元素编号框和鼠标位置。先缩放再绘制，保证编号文字清晰。"""

from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .coords import Frame
from .types import Element

_COLORS = [
    (230, 25, 75), (60, 140, 60), (0, 110, 220), (245, 130, 48), (145, 30, 180),
    (0, 150, 150), (200, 30, 160), (128, 100, 0), (0, 0, 128), (170, 60, 60),
]


@lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.ImageFont:
    for name in ("arialbd.ttf", "arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_elements(image: Image.Image, frame: Frame, numbered: list[tuple[int, Element]]) -> None:
    """numbered 为 (编号, 元素) 列表；元素框超出图片的部分会被自然裁掉。"""
    draw = ImageDraw.Draw(image)
    font = _font(max(11, round(min(image.size) / 70)))
    for index, el in numbered:
        el_rect = el.rect.intersect(frame.region)
        if el_rect.is_empty():
            continue
        color = _COLORS[index % len(_COLORS)]
        x1, y1 = frame.to_image_px(el_rect.left, el_rect.top)
        x2, y2 = frame.to_image_px(el_rect.right, el_rect.bottom)
        draw.rectangle((x1, y1, max(x1, x2 - 1), max(y1, y2 - 1)), outline=color, width=2)

        label = str(index)
        tl, tt, tr, tb = draw.textbbox((0, 0), label, font=font)
        tw, th = tr - tl + 4, tb - tt + 2
        # 标签放在框的左上角外侧，贴顶时放到框内
        ly = y1 - th if y1 - th >= 0 else y1
        lx = max(0, min(x1, image.width - tw))
        draw.rectangle((lx, ly, lx + tw, ly + th), fill=color)
        draw.text((lx + 2 - tl, ly + 1 - tt), label, fill=(255, 255, 255), font=font)


def draw_cursor(image: Image.Image, frame: Frame, sx: int, sy: int) -> None:
    if not frame.region.contains(sx, sy):
        return
    x, y = frame.to_image_px(sx, sy)
    r = max(6, round(min(image.size) / 90))
    draw = ImageDraw.Draw(image)
    for width, color in ((4, (255, 255, 255)), (2, (255, 0, 0))):
        draw.line((x - r, y, x + r, y), fill=color, width=width)
        draw.line((x, y - r, x, y + r), fill=color, width=width)
