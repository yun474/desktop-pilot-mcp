"""注册给大模型的桌面操作工具。

工具类必须定义在插件包内，AstrBot 才能根据模块路径把它们归属到本插件，卸载插件时一并移除。
"""

from __future__ import annotations

from typing import Any, ClassVar

import mcp.types
from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import logger
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

_IMAGE_NOTE = "（截图仅供你观察屏幕，除非用户要求，否则不需要发给用户）"
_COORD_NOTE = "坐标以最近一次 desktop_screenshot 或 desktop_zoom 返回的图片为准，具体取值范围见该结果中的“坐标规则”"

_LABEL = {"type": "integer", "description": "目标元素编号（截图中方框上的数字）。优先使用编号"}
_X = {"type": "number", "description": f"目标横坐标，没有编号时使用。{_COORD_NOTE}"}
_Y = {"type": "number", "description": "目标纵坐标，与 x 配合使用"}


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


def _opt(value: Any, cast: type, default: Any = None) -> Any:
    """把模型传来的可选参数转换为目标类型，空值视为未提供。"""
    if value is None or value == "":
        return default
    return cast(value)


def _bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


@dataclass
class DesktopTool(FunctionTool[AstrAgentContext]):
    runtime: ClassVar[Any] = None  # 由插件初始化时注入 PilotRuntime

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        runtime = DesktopTool.runtime
        if runtime is None:
            return "桌面操控插件未就绪"
        denied = runtime.check_permission(context.context.event)
        if denied:
            return denied
        try:
            out = await runtime.worker.run(self.run_sync, runtime.session, **kwargs)
        except (ValueError, LookupError, PermissionError, RuntimeError, OSError) as e:
            return f"操作失败：{e}"
        except Exception as e:
            logger.exception(f"[desktop_pilot] 工具 {self.name} 执行异常")
            return f"操作失败：{type(e).__name__}: {e}"
        if out.image_b64 is None:
            return out.text
        return mcp.types.CallToolResult(
            content=[
                mcp.types.TextContent(type="text", text=out.text + _IMAGE_NOTE),
                mcp.types.ImageContent(type="image", data=out.image_b64, mimeType=out.mime),
            ]
        )

    def run_sync(self, session, **kwargs):
        raise NotImplementedError


@dataclass
class ScreenshotTool(DesktopTool):
    name: str = "desktop_screenshot"
    description: str = (
        "截取电脑屏幕，返回截图和可交互元素列表。截图上每个可点击的元素都有带编号的彩色方框，"
        "操作时优先使用编号。每次操作前后、界面发生变化后都应重新截图确认。"
    )
    parameters: dict = Field(default_factory=lambda: _schema({
        "display": {"type": "integer", "description": "显示器编号：0=前台窗口所在显示器（默认），-1=全部显示器，1、2…=指定显示器"},
        "annotate": {"type": "boolean", "description": "是否标注元素编号，默认按插件配置"},
        "wait_seconds": {"type": "number", "description": "截图前等待的秒数（最多 10），用于等待程序加载或动画结束"},
    }))

    def run_sync(self, session, display=None, annotate=None, wait_seconds=None, **_):
        return session.screenshot(_opt(display, int), None if annotate is None else _bool(annotate),
                                  _opt(wait_seconds, float, 0))


@dataclass
class ZoomTool(DesktopTool):
    name: str = "desktop_zoom"
    description: str = (
        "放大查看最近一张图片中的矩形区域，用于看清小字、小图标或精确定位。"
        "返回放大图后，后续坐标改为以放大图为准，直到下次截图。"
    )
    parameters: dict = Field(default_factory=lambda: _schema({
        "x1": {"type": "number", "description": f"区域左上角横坐标。{_COORD_NOTE}"},
        "y1": {"type": "number", "description": "区域左上角纵坐标"},
        "x2": {"type": "number", "description": "区域右下角横坐标"},
        "y2": {"type": "number", "description": "区域右下角纵坐标"},
    }, ["x1", "y1", "x2", "y2"]))

    def run_sync(self, session, x1, y1, x2, y2, **_):
        return session.zoom(float(x1), float(y1), float(x2), float(y2))


@dataclass
class ClickTool(DesktopTool):
    name: str = "desktop_click"
    description: str = "鼠标点击元素或坐标。提供 label（元素编号），或者同时提供 x 和 y。"
    parameters: dict = Field(default_factory=lambda: _schema({
        "label": _LABEL,
        "x": _X,
        "y": _Y,
        "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "鼠标按键，默认 left"},
        "clicks": {"type": "integer", "description": "点击次数：1=单击（默认），2=双击，0=只移动鼠标不点击"},
    }))

    def run_sync(self, session, label=None, x=None, y=None, button="left", clicks=1, **_):
        return session.click(_opt(label, int), _opt(x, float), _opt(y, float),
                             button or "left", _opt(clicks, int, 1))


@dataclass
class TypeTool(DesktopTool):
    name: str = "desktop_type"
    description: str = (
        "在输入框中输入文字，支持中文。提供 label 或 x、y 时会先点击该位置再输入；都不提供则输入到当前焦点处。"
    )
    parameters: dict = Field(default_factory=lambda: _schema({
        "text": {"type": "string", "description": "要输入的文字，\\n 表示换行"},
        "label": _LABEL,
        "x": _X,
        "y": _Y,
        "clear": {"type": "boolean", "description": "输入前是否先清空原有内容（Ctrl+A 后删除），默认 false"},
        "press_enter": {"type": "boolean", "description": "输入后是否按回车，默认 false"},
    }, ["text"]))

    def run_sync(self, session, text, label=None, x=None, y=None, clear=False, press_enter=False, **_):
        return session.type_text(str(text), _opt(label, int), _opt(x, float), _opt(y, float),
                                 _bool(clear), _bool(press_enter))


@dataclass
class ScrollTool(DesktopTool):
    name: str = "desktop_scroll"
    description: str = "在元素或坐标处滚动鼠标滚轮；都不提供时在当前鼠标位置滚动。"
    parameters: dict = Field(default_factory=lambda: _schema({
        "direction": {"type": "string", "enum": ["up", "down", "left", "right"], "description": "滚动方向"},
        "amount": {"type": "integer", "description": "滚动格数，默认 3"},
        "label": _LABEL,
        "x": _X,
        "y": _Y,
    }, ["direction"]))

    def run_sync(self, session, direction, amount=3, label=None, x=None, y=None, **_):
        return session.scroll(str(direction), _opt(amount, int, 3), _opt(label, int),
                              _opt(x, float), _opt(y, float))


@dataclass
class DragTool(DesktopTool):
    name: str = "desktop_drag"
    description: str = "按住鼠标左键从起点拖拽到终点，用于拖动文件、滑块、选中文本等。"
    parameters: dict = Field(default_factory=lambda: _schema({
        "x1": {"type": "number", "description": f"起点横坐标。{_COORD_NOTE}"},
        "y1": {"type": "number", "description": "起点纵坐标"},
        "x2": {"type": "number", "description": "终点横坐标"},
        "y2": {"type": "number", "description": "终点纵坐标"},
    }, ["x1", "y1", "x2", "y2"]))

    def run_sync(self, session, x1, y1, x2, y2, **_):
        return session.drag(float(x1), float(y1), float(x2), float(y2))


@dataclass
class HotkeyTool(DesktopTool):
    name: str = "desktop_hotkey"
    description: str = (
        "按下键盘按键或组合键，用 + 连接，例如 enter、esc、ctrl+c、ctrl+shift+t、alt+tab、win+d、f5。"
    )
    parameters: dict = Field(default_factory=lambda: _schema({
        "keys": {"type": "string", "description": "按键或组合键"},
    }, ["keys"]))

    def run_sync(self, session, keys, **_):
        return session.hotkey(str(keys))


@dataclass
class AppTool(DesktopTool):
    name: str = "desktop_app"
    description: str = (
        "管理应用程序：list=列出已打开的窗口，switch=按名称切换到某个窗口，launch=按名称从开始菜单启动应用。"
    )
    parameters: dict = Field(default_factory=lambda: _schema({
        "action": {"type": "string", "enum": ["list", "switch", "launch"], "description": "操作类型"},
        "name": {"type": "string", "description": "窗口标题或应用名称（switch、launch 时必填），支持模糊匹配"},
    }, ["action"]))

    def run_sync(self, session, action, name="", **_):
        return session.app(str(action), str(name or ""))


ALL_TOOLS = (ScreenshotTool, ZoomTool, ClickTool, TypeTool, ScrollTool, DragTool, HotkeyTool, AppTool)
