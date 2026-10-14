"""读取 config.toml。配置文件不存在时从 config.example.toml 生成，并自动填入随机 token。"""

from __future__ import annotations

import re
import secrets
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .core.coords import NORMALIZED, PIXEL
from .core.session import PilotConfig

EXAMPLE_NAME = "config.example.toml"
_NAME_RE = re.compile(r"^[A-Za-z0-9_]*$")
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


TOOL_SWITCHES = ("multi", "clipboard", "notify", "shell", "file", "registry", "process", "scrape")


@dataclass
class ToolsConfig:
    enabled: dict[str, bool]
    shell_timeout: int = 30
    shell_max_timeout: int = 300
    output_limit: int = 20000


@dataclass
class ServerConfig:
    name: str
    host: str
    port: int
    token: str


def ensure_config(path: Path) -> bool:
    """配置文件不存在时生成一份，返回是否新生成。"""
    if path.exists():
        return False
    example = path.with_name(EXAMPLE_NAME)
    if not example.exists():
        raise FileNotFoundError(f"找不到配置文件 {path}，也找不到模板 {example}")
    text = example.read_text(encoding="utf-8")
    text = re.sub(r'(?m)^token = ""', f'token = "{secrets.token_urlsafe(32)}"', text, count=1)
    path.write_text(text, encoding="utf-8")
    return True


def load_config(path: Path) -> tuple[ServerConfig, PilotConfig, ToolsConfig]:
    with path.open("rb") as f:
        data = tomllib.load(f)
    srv = data.get("server", {})
    desk = data.get("desktop", {})
    tls = data.get("tools", {})

    server = ServerConfig(
        name=str(srv.get("name", "")).strip(),
        host=str(srv.get("host", "127.0.0.1")).strip(),
        port=int(srv.get("port", 8765)),
        token=str(srv.get("token", "")).strip(),
    )
    if not _NAME_RE.match(server.name):
        raise ValueError(f"server.name 只能包含字母、数字和下划线，当前是「{server.name}」")
    if not server.token and server.host not in _LOOPBACK:
        raise ValueError("监听非本机地址时必须设置 server.token，否则任何能连上这台电脑的设备都能操控它")

    pilot = PilotConfig(
        coord_mode=PIXEL if desk.get("coord_mode") == PIXEL else NORMALIZED,
        max_long_edge=max(512, int(desk.get("max_long_edge", 1280))),
        image_format="png" if desk.get("image_format") == "png" else "jpeg",
        jpeg_quality=min(95, max(30, int(desk.get("jpeg_quality", 80)))),
        annotate=bool(desk.get("annotate", True)),
        max_elements=max(10, int(desk.get("max_elements", 120))),
        element_timeout=max(0.5, float(desk.get("element_timeout", 3.0))),
        default_display=int(desk.get("default_display", 0)),
        type_method="paste" if desk.get("type_method") == "paste" else "unicode",
        screenshot_after_action=bool(desk.get("screenshot_after_action", False)),
        action_delay=max(0.0, float(desk.get("action_delay", 0.6))),
        blocked_hotkeys=[str(k) for k in desk.get("blocked_hotkeys", ["win+l", "ctrl+alt+delete"])],
    )
    tools = ToolsConfig(
        enabled={key: bool(tls.get(key, True)) for key in TOOL_SWITCHES},
        shell_timeout=max(1, int(tls.get("shell_timeout", 30))),
        shell_max_timeout=max(1, int(tls.get("shell_max_timeout", 300))),
        output_limit=max(1000, int(tls.get("output_limit", 20000))),
    )
    return server, pilot, tools
