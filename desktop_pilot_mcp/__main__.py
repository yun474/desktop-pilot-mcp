"""命令行入口：python -m desktop_pilot_mcp [--config config.toml]"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from .config import ensure_config, load_config
from .server import build_app

logger = logging.getLogger("desktop_pilot_mcp")


def _setup_logging(log_file: Path) -> None:
    handlers: list[logging.Handler] = [
        RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    ]
    # pythonw 后台运行时没有控制台，sys.stderr 为 None
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="desktop-pilot-mcp", description="通过截图操控 Windows 桌面的 MCP 服务器")
    parser.add_argument("--config", default="config.toml", help="配置文件路径，默认为当前目录下的 config.toml")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    _setup_logging(config_path.with_name("desktop-pilot.log"))
    try:
        created = ensure_config(config_path)
        server_cfg, pilot_cfg, tools_cfg = load_config(config_path)
    except Exception as e:
        logger.error("配置错误：%s", e)
        sys.exit(1)
    if created:
        logger.info("已生成配置文件 %s，并自动创建了访问令牌", config_path)

    app, worker, tool_names = build_app(server_cfg, pilot_cfg, tools_cfg)
    server_key = server_cfg.name or "desktop"
    host = "<这台电脑的 Tailscale IP>" if server_cfg.host in ("0.0.0.0", "::") else server_cfg.host
    snippet = {
        "transport": "streamable_http",
        "url": f"http://{host}:{server_cfg.port}/mcp",
        "headers": {"Authorization": f"Bearer {server_cfg.token}"} if server_cfg.token else {},
    }
    logger.info("监听 %s:%d，工具：%s", server_cfg.host, server_cfg.port, ", ".join(tool_names))
    # 令牌只打印到控制台，不写入日志文件
    print(f"\nAstrBot 中添加 MCP 服务器「{server_key}」时使用以下配置：\n"
          f"{json.dumps(snippet, ensure_ascii=False, indent=2)}\n", flush=True)
    try:
        uvicorn.run(app, host=server_cfg.host, port=server_cfg.port, log_config=None, log_level="info")
    finally:
        worker.shutdown()


if __name__ == "__main__":
    main()
