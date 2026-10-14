"""MCP 服务端：组装各组工具，并用 Bearer token 保护 HTTP 接口。"""

from __future__ import annotations

import hmac

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

from .config import ServerConfig, ToolsConfig
from .core.session import DesktopSession, PilotConfig
from .core.worker import DesktopWorker
from .tools import desktop, system, web
from .tools.common import Registrar, naming


def build_server(server_cfg: ServerConfig, pilot_cfg: PilotConfig,
                 tools_cfg: ToolsConfig) -> tuple[FastMCP, DesktopWorker, list[str]]:
    prefix, tag = naming(server_cfg.name)
    mcp = FastMCP(
        "desktop-pilot",
        instructions=(
            f"{tag}操控一台 Windows 电脑。操作界面时先调用 {prefix}screenshot 观察屏幕，"
            "优先按元素编号操作；没有编号时使用坐标，坐标由服务端自动换算，无需自行计算缩放。"
        ),
        host=server_cfg.host,
        port=server_cfg.port,
        stateless_http=True,
        json_response=True,
    )
    reg = Registrar(mcp, server_cfg.name)
    session = DesktopSession(pilot_cfg, reg.prefix)
    worker = DesktopWorker()
    desktop.register(reg, session, worker, tools_cfg)
    system.register(reg, tools_cfg)
    web.register(reg, tools_cfg)
    return mcp, worker, reg.names


class BearerAuth:
    """纯 ASGI 中间件，校验 Authorization: Bearer <token>。不缓冲响应，不影响流式传输。"""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.expected = f"Bearer {token}".encode()
        self.enabled = bool(token)

    async def __call__(self, scope, receive, send) -> None:
        if self.enabled and scope["type"] == "http":
            got = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(got, self.expected):
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_app(server_cfg: ServerConfig, pilot_cfg: PilotConfig, tools_cfg: ToolsConfig):
    mcp, worker, tool_names = build_server(server_cfg, pilot_cfg, tools_cfg)
    return BearerAuth(mcp.streamable_http_app(), server_cfg.token), worker, tool_names
