"""桌面操作工具：截图、点击、输入等，全部在 DesktopWorker 线程中串行执行。"""

import asyncio
from typing import Annotated, Any, Callable, Literal

from mcp.types import ImageContent, TextContent
from pydantic import Field

from ..config import ToolsConfig
from ..core import notify
from ..core.session import DesktopSession, ToolOutput
from ..core.worker import DesktopWorker
from .common import COORD_NOTE, Content, Label, Registrar, X, Y, guarded, optional, text

_IMAGE_NOTE = "（截图仅供你观察屏幕，除非用户要求，否则不需要发给用户）"


def _content(out: ToolOutput) -> Content:
    if out.image_b64 is None:
        return text(out.text)
    return [
        TextContent(type="text", text=out.text + _IMAGE_NOTE),
        ImageContent(type="image", data=out.image_b64, mimeType=out.mime),
    ]


def register(reg: Registrar, session: DesktopSession, worker: DesktopWorker, tools_cfg: ToolsConfig) -> None:
    async def run(func: Callable[..., ToolOutput], *args: Any) -> Content:
        return _content(await guarded(worker.run(func, *args)))

    p = reg.prefix

    @reg.tool("screenshot", "截取电脑屏幕，返回截图和可交互元素列表。截图上每个可点击的元素都有带编号的彩色方框，"
                            "操作时优先使用编号。每次操作前后、界面发生变化后都应重新截图确认。", read_only=True)
    async def screenshot(
        display: Annotated[int | None, optional("integer", "显示器编号：0=前台窗口所在显示器（默认），-1=全部显示器，1、2…=指定显示器")] = None,
        annotate: Annotated[bool | None, optional("boolean", "是否标注元素编号，默认按服务端配置")] = None,
        wait_seconds: Annotated[float, Field(description="截图前等待的秒数（最多 10），用于等待程序加载或动画结束")] = 0,
    ) -> Content:
        return await run(session.screenshot, display, annotate, wait_seconds)

    @reg.tool("zoom", "放大查看最近一张图片中的矩形区域，用于看清小字、小图标或精确定位。"
                      "返回放大图后，后续坐标改为以放大图为准，直到下次截图；元素编号不变。", read_only=True)
    async def zoom(
        x1: Annotated[float, Field(description=f"区域左上角横坐标。{COORD_NOTE}")],
        y1: Annotated[float, Field(description="区域左上角纵坐标")],
        x2: Annotated[float, Field(description="区域右下角横坐标")],
        y2: Annotated[float, Field(description="区域右下角纵坐标")],
    ) -> Content:
        return await run(session.zoom, x1, y1, x2, y2)

    @reg.tool("click", "鼠标点击元素或坐标。提供 label（元素编号），或者同时提供 x 和 y。")
    async def click(
        label: Label = None,
        x: X = None,
        y: Y = None,
        button: Annotated[Literal["left", "right", "middle"], Field(description="鼠标按键")] = "left",
        clicks: Annotated[int, Field(description="点击次数：1=单击，2=双击，0=只移动鼠标不点击")] = 1,
    ) -> Content:
        return await run(session.click, label, x, y, button, clicks)

    @reg.tool("type", "在输入框中输入文字，支持中文。提供 label 或 x、y 时会先点击该位置再输入；都不提供则输入到当前焦点处。")
    async def type_text(
        text: Annotated[str, Field(description="要输入的文字，\\n 表示换行")],
        label: Label = None,
        x: X = None,
        y: Y = None,
        clear: Annotated[bool, Field(description="输入前是否先清空原有内容（Ctrl+A 后删除）")] = False,
        press_enter: Annotated[bool, Field(description="输入后是否按回车")] = False,
    ) -> Content:
        return await run(session.type_text, text, label, x, y, clear, press_enter)

    @reg.tool("scroll", "在元素或坐标处滚动鼠标滚轮；都不提供时在当前鼠标位置滚动。")
    async def scroll(
        direction: Annotated[Literal["up", "down", "left", "right"], Field(description="滚动方向")],
        amount: Annotated[int, Field(description="滚动格数")] = 3,
        label: Label = None,
        x: X = None,
        y: Y = None,
    ) -> Content:
        return await run(session.scroll, direction, amount, label, x, y)

    @reg.tool("drag", "按住鼠标左键从起点拖拽到终点，用于拖动文件、滑块、选中文本等。")
    async def drag(
        x1: Annotated[float, Field(description=f"起点横坐标。{COORD_NOTE}")],
        y1: Annotated[float, Field(description="起点纵坐标")],
        x2: Annotated[float, Field(description="终点横坐标")],
        y2: Annotated[float, Field(description="终点纵坐标")],
    ) -> Content:
        return await run(session.drag, x1, y1, x2, y2)

    @reg.tool("hotkey", "按下键盘按键或组合键，用 + 连接，例如 enter、esc、ctrl+c、ctrl+shift+t、alt+tab、win+d、f5。")
    async def hotkey(keys: Annotated[str, Field(description="按键或组合键")]) -> Content:
        return await run(session.hotkey, keys)

    @reg.tool("app", "管理应用程序和窗口：list=列出已打开的窗口，switch=切换到某个窗口，launch=从开始菜单启动应用，"
                     "maximize/minimize/restore=最大化/最小化/还原窗口，"
                     "resize=把窗口移动到指定位置和大小（x、y、width、height 与截图坐标同一单位）。"
                     "maximize/minimize/restore/resize 不提供 name 时操作前台窗口。")
    async def app(
        action: Annotated[Literal["list", "switch", "launch", "maximize", "minimize", "restore", "resize"],
                          Field(description="操作类型")],
        name: Annotated[str, Field(description="窗口标题或应用名称，支持模糊匹配")] = "",
        x: Annotated[float | None, optional("number", f"resize 时窗口左上角横坐标。{COORD_NOTE}")] = None,
        y: Annotated[float | None, optional("number", "resize 时窗口左上角纵坐标")] = None,
        width: Annotated[float | None, optional("number", "resize 时窗口宽度")] = None,
        height: Annotated[float | None, optional("number", "resize 时窗口高度")] = None,
    ) -> Content:
        return await run(session.app, action, name, x, y, width, height)

    @reg.tool("wait", "等待指定秒数（最多 60），用于等待程序启动、页面加载或动画结束。", read_only=True)
    async def wait(seconds: Annotated[float, Field(description="等待秒数")]) -> Content:
        seconds = max(0.0, min(float(seconds), 60.0))
        await asyncio.sleep(seconds)
        return text(f"已等待 {seconds:g} 秒，需要确认界面时请调用 {p}screenshot")

    if tools_cfg.enabled["multi"]:
        @reg.tool("multi_click", "依次点击多个元素或坐标。hold_ctrl=true 时按住 Ctrl 点击，用于多选文件、列表项。")
        async def multi_click(
            labels: Annotated[list[int] | None, optional("array", "元素编号列表", items={"type": "integer"})] = None,
            points: Annotated[list[list[float]] | None, optional(
                "array", f"坐标列表，每项为 [x, y]。{COORD_NOTE}",
                items={"type": "array", "items": {"type": "number"}})] = None,
            hold_ctrl: Annotated[bool, Field(description="是否按住 Ctrl 点击")] = False,
        ) -> Content:
            return await run(session.multi_click, labels, points, hold_ctrl)

        @reg.tool("multi_type", "依次在多个输入框中输入文字，适合一次填写表单。每项提供 label 或 x、y，以及 text。")
        async def multi_type(
            items: Annotated[list[dict[str, Any]], optional("array", "输入项列表", items={
                "type": "object",
                "properties": {
                    "label": {"type": "integer", "description": "元素编号"},
                    "x": {"type": "number", "description": "横坐标，没有编号时使用"},
                    "y": {"type": "number", "description": "纵坐标"},
                    "text": {"type": "string", "description": "要输入的文字"},
                },
                "required": ["text"],
            })],
            clear: Annotated[bool, Field(description="输入前是否先清空各输入框原有内容")] = False,
        ) -> Content:
            return await run(session.multi_type, items, clear)

    if tools_cfg.enabled["clipboard"]:
        @reg.tool("clipboard", "读取或写入剪贴板文本：get=读取，set=写入。")
        async def clipboard(
            action: Annotated[Literal["get", "set"], Field(description="操作类型")],
            text: Annotated[str, Field(description="set 时要写入的文字")] = "",
        ) -> Content:
            return await run(session.clipboard, action, text)

    if tools_cfg.enabled["notify"]:
        @reg.tool("notify", "在电脑右下角弹出系统通知，用于提醒电脑前的人。")
        async def send_notify(
            title: Annotated[str, Field(description="通知标题")],
            message: Annotated[str, Field(description="通知正文")],
        ) -> Content:
            await guarded(asyncio.to_thread(notify.send_toast, title, message))
            return text(f"已发送通知「{title}」")
