"""工具注册的公共部分：名称前缀、参数类型、错误转换。"""

from __future__ import annotations

from typing import Annotated, Any, Awaitable

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ImageContent, TextContent, ToolAnnotations
from pydantic import WithJsonSchema

Content = list[TextContent | ImageContent]

# 这些异常的消息都是写给模型看的中文提示，直接作为工具错误返回
EXPECTED_ERRORS = (ValueError, LookupError, PermissionError, RuntimeError, OSError)

COORD_NOTE = "坐标以最近一次截图或放大图为准，取值范围见该结果中的“坐标规则”"


def optional(json_type: str, description: str, **extra: Any):
    """可选参数：校验时允许缺省，但 schema 只声明基础类型，避免部分模型不支持 anyOf/null。"""
    return WithJsonSchema({"type": json_type, "description": description, **extra})


Label = Annotated[int | None, optional("integer", "目标元素编号（截图中方框上的数字），优先使用")]
X = Annotated[float | None, optional("number", f"目标横坐标，没有编号时使用。{COORD_NOTE}")]
Y = Annotated[float | None, optional("number", "目标纵坐标，与 x 配合使用")]


def text(content: str) -> Content:
    return [TextContent(type="text", text=content)]


async def guarded(awaitable: Awaitable[Any]) -> Any:
    try:
        return await awaitable
    except EXPECTED_ERRORS as e:
        raise ToolError(str(e)) from e


def naming(name: str) -> tuple[str, str]:
    """返回 (工具名前缀, 描述标签)。"""
    return (f"{name}_", f"【电脑：{name}】") if name else ("desktop_", "")


class Registrar:
    """统一给工具加电脑名前缀、描述标签和风险标注。"""

    def __init__(self, mcp: FastMCP, name: str) -> None:
        self.mcp = mcp
        self.prefix, self.tag = naming(name)
        self.names: list[str] = []

    def tool(self, suffix: str, description: str, *, read_only: bool = False, destructive: bool = False):
        def register(fn):
            name = self.prefix + suffix
            self.mcp.add_tool(
                fn,
                name=name,
                description=self.tag + description,
                annotations=ToolAnnotations(readOnlyHint=read_only, destructiveHint=destructive),
                structured_output=False,
            )
            self.names.append(name)
            return fn
        return register
