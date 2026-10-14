"""坐标换算单元测试：python -m pytest tests"""

import pytest

from desktop_pilot_mcp.core.coords import NORMALIZED, PIXEL, Frame, fit_size
from desktop_pilot_mcp.core.types import Rect

# 2560x1600 屏幕缩到 1280x800
SCREEN = Frame(1, Rect(0, 0, 2560, 1600), 1280, 800)
# 副屏在主屏左侧（负坐标）
LEFT_MONITOR = Frame(2, Rect(-1920, 0, 0, 1080), 1280, 720)


def test_fit_size():
    assert fit_size(2560, 1600, 1280) == (1280, 800)
    assert fit_size(1000, 500, 1280) == (1000, 500)  # 不放大
    assert fit_size(200, 100, 1280, max_upscale=3.0) == (600, 300)


def test_normalized_center_and_corners():
    assert SCREEN.to_screen(500, 500, NORMALIZED) == (1280, 800)
    assert SCREEN.to_screen(0, 0, NORMALIZED) == (0, 0)
    assert SCREEN.to_screen(1000, 1000, NORMALIZED) == (2559, 1599)


def test_pixel_mode_scales_back():
    assert SCREEN.to_screen(640, 400, PIXEL) == (1280, 800)
    assert SCREEN.to_screen(100, 50, PIXEL) == (200, 100)


def test_negative_monitor_offset():
    assert LEFT_MONITOR.to_screen(500, 500, NORMALIZED) == (-960, 540)
    assert LEFT_MONITOR.from_screen(-960, 540, NORMALIZED) == (500, 500)


def test_round_trip():
    for mode in (NORMALIZED, PIXEL):
        for sx, sy in ((0, 0), (1234, 567), (2559, 1599)):
            mx, my = SCREEN.from_screen(sx, sy, mode)
            bx, by = SCREEN.to_screen(mx, my, mode)
            assert abs(bx - sx) <= 3 and abs(by - sy) <= 3


def test_out_of_range():
    with pytest.raises(ValueError):
        SCREEN.to_screen(1001, 10, NORMALIZED)
    with pytest.raises(ValueError):
        SCREEN.to_screen(1281, 10, PIXEL)


def test_zoom_sub_region_chain():
    # 放大右下角四分之一，再在放大图中心点击，应落在屏幕 (1920, 1200)
    region = SCREEN.sub_region(500, 500, 1000, 1000, NORMALIZED)
    assert region == Rect(1280, 800, 2560, 1600)
    w, h = fit_size(region.width, region.height, 1280, 3.0)
    zoom = Frame(3, region, w, h, "zoom")
    assert zoom.to_screen(500, 500, NORMALIZED) == (1920, 1200)
