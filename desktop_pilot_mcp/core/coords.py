"""模型坐标与屏幕物理坐标之间的换算。

每次返回给模型的图片（截图或放大图）都对应一个 Frame，记录它覆盖的屏幕区域和图片尺寸。
模型报出的坐标总是相对于“最近一张图片”，由这里换算成真实屏幕坐标，模型无需自行计算缩放。
本模块不依赖 Windows API，可单独测试。
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import Rect

NORMALIZED = "normalized"  # 0~1000 千分比坐标
PIXEL = "pixel"  # 图片像素坐标
NORM_MAX = 1000


@dataclass(frozen=True)
class Frame:
    frame_id: int
    region: Rect  # 图片覆盖的屏幕区域（物理像素）
    image_width: int
    image_height: int
    kind: str = "screenshot"  # "screenshot" | "zoom"

    def _limits(self, mode: str) -> tuple[float, float]:
        if mode == NORMALIZED:
            return NORM_MAX, NORM_MAX
        return self.image_width, self.image_height

    def to_screen(self, x: float, y: float, mode: str) -> tuple[int, int]:
        """模型坐标 -> 屏幕物理坐标。越界时抛出 ValueError。"""
        max_x, max_y = self._limits(mode)
        if not (0 <= x <= max_x and 0 <= y <= max_y):
            raise ValueError(
                f"坐标 ({x}, {y}) 超出范围，当前图片的有效范围是 x: 0~{max_x:g}，y: 0~{max_y:g}"
            )
        r = self.region
        sx = r.left + int(x / max_x * r.width)
        sy = r.top + int(y / max_y * r.height)
        # 右/下边界取值会落在区域外一个像素，夹回区域内
        return min(sx, r.right - 1), min(sy, r.bottom - 1)

    def from_screen(self, sx: int, sy: int, mode: str) -> tuple[int, int]:
        """屏幕物理坐标 -> 模型坐标（四舍五入），用于向模型回报位置。"""
        max_x, max_y = self._limits(mode)
        r = self.region
        return (
            round((sx - r.left) / r.width * max_x),
            round((sy - r.top) / r.height * max_y),
        )

    def to_image_px(self, sx: int, sy: int) -> tuple[int, int]:
        """屏幕物理坐标 -> 图片像素坐标，用于在图片上绘制标注。"""
        return self.from_screen(sx, sy, PIXEL)

    def sub_region(self, x1: float, y1: float, x2: float, y2: float, mode: str) -> Rect:
        """把模型给出的矩形（两个角点）换算成屏幕区域，用于放大查看。"""
        ax, ay = self.to_screen(min(x1, x2), min(y1, y2), mode)
        self.to_screen(max(x1, x2), max(y1, y2), mode)  # 仅做越界校验
        max_x, max_y = self._limits(mode)
        r = self.region
        # 右下角按区域边界计算（不夹回区域内），保证框选整图时得到完整区域
        bx = r.left + round(max(x1, x2) / max_x * r.width)
        by = r.top + round(max(y1, y2) / max_y * r.height)
        return Rect(ax, ay, max(bx, ax + 1), max(by, ay + 1))


def fit_size(width: int, height: int, max_long_edge: int, max_upscale: float = 1.0) -> tuple[int, int]:
    """计算缩放后的图片尺寸：长边不超过 max_long_edge，放大倍数不超过 max_upscale。"""
    scale = min(max_long_edge / max(width, height), max_upscale)
    return max(1, round(width * scale)), max(1, round(height * scale))


def describe_mode(mode: str, frame: Frame) -> str:
    if mode == NORMALIZED:
        return "千分比坐标：x、y 都取 0~1000，左上角是 (0,0)，右下角是 (1000,1000)，与图片实际像素无关"
    return f"图片像素坐标：x 取 0~{frame.image_width}，y 取 0~{frame.image_height}，左上角是 (0,0)"
