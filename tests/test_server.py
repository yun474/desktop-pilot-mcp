"""配置读取与令牌校验测试。"""

import shutil
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from desktop_pilot_mcp.config import ensure_config, load_config
from desktop_pilot_mcp.server import BearerAuth

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.toml"


def _write(tmp_path: Path, server: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(f"[server]\n{server}\n", encoding="utf-8")
    return path


def test_ensure_config_generates_token(tmp_path):
    shutil.copy(EXAMPLE, tmp_path / EXAMPLE.name)
    path = tmp_path / "config.toml"
    assert ensure_config(path) is True
    server, pilot, tools = load_config(path)
    assert len(server.token) >= 32
    assert server.name == "laptop" and pilot.coord_mode == "normalized"
    assert all(tools.enabled.values()) and tools.shell_timeout == 30
    # 已存在时不覆盖
    assert ensure_config(path) is False
    assert load_config(path)[0].token == server.token


def test_remote_host_requires_token(tmp_path):
    with pytest.raises(ValueError, match="token"):
        load_config(_write(tmp_path, 'host = "0.0.0.0"\ntoken = ""'))
    # 仅本机监听时允许不设令牌
    assert load_config(_write(tmp_path, 'host = "127.0.0.1"\ntoken = ""'))[0].token == ""


def test_invalid_name(tmp_path):
    with pytest.raises(ValueError, match="name"):
        load_config(_write(tmp_path, 'name = "my-pc"\ntoken = "x"'))


def test_bearer_auth():
    inner = Starlette(routes=[Route("/mcp", lambda r: PlainTextResponse("ok"), methods=["POST"])])
    client = TestClient(BearerAuth(inner, "secret"))
    assert client.post("/mcp").status_code == 401
    assert client.post("/mcp", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/mcp", headers={"Authorization": "Bearer secret"}).text == "ok"
