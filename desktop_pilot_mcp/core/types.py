"""公共数据结构。所有矩形与坐标均为物理像素、虚拟桌面坐标系。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    def intersect(self, other: Rect) -> Rect:
        return Rect(
            max(self.left, other.left),
            max(self.top, other.top),
            min(self.right, other.right),
            min(self.bottom, other.bottom),
        )

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


@dataclass
class Element:
    """一个可交互的界面元素。"""

    name: str
    control_type: str  # 例如 "Button"、"Edit"，去掉 "Control" 后缀
    rect: Rect  # 物理像素，已与截图区域求交
    window_title: str  # 所属顶层窗口标题
    hwnd: int = 0  # 所属顶层窗口句柄
    value: str = ""  # 输入框等控件的当前值（可选，截断）


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    process_name: str
    rect: Rect
    is_foreground: bool
    is_minimized: bool
