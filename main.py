import sys

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star


class PilotRuntime:
    """插件运行时：桌面会话、专用线程与权限判定。"""

    def __init__(self, config: AstrBotConfig) -> None:
        from .core.session import DesktopSession, PilotConfig
        from .core.worker import DesktopWorker

        mode = config.get("coord_mode", "normalized")
        self.session = DesktopSession(
            PilotConfig(
                coord_mode="pixel" if mode == "pixel" else "normalized",
                max_long_edge=max(512, int(config.get("max_long_edge", 1280))),
                image_format="png" if config.get("image_format") == "png" else "jpeg",
                jpeg_quality=min(95, max(30, int(config.get("jpeg_quality", 80)))),
                annotate=bool(config.get("annotate", True)),
                max_elements=max(10, int(config.get("max_elements", 120))),
                element_timeout=max(0.5, float(config.get("element_timeout", 3.0))),
                default_display=int(config.get("default_display", 0)),
                type_method="paste" if config.get("type_method") == "paste" else "unicode",
                screenshot_after_action=bool(config.get("screenshot_after_action", False)),
                action_delay=max(0.0, float(config.get("action_delay", 0.6))),
                blocked_hotkeys=list(config.get("blocked_hotkeys", ["win+l", "ctrl+alt+delete"])),
            )
        )
        self.worker = DesktopWorker()
        self.admin_only = bool(config.get("admin_only", True))
        self.allowed_users = {str(u).strip() for u in config.get("allowed_users", []) if str(u).strip()}

    def check_permission(self, event: AstrMessageEvent) -> str | None:
        if str(event.get_sender_id()) in self.allowed_users:
            return None
        if self.admin_only and not event.is_admin():
            return "权限不足：只有管理员或白名单用户可以操控电脑。请直接告诉用户没有权限，不要重试。"
        return None


class DesktopPilot(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.runtime: PilotRuntime | None = None
        if sys.platform != "win32":
            logger.error("[desktop_pilot] 本插件仅支持 Windows，未注册任何工具")
            return

        from .tools import ALL_TOOLS, DesktopTool

        self.runtime = PilotRuntime(config)
        DesktopTool.runtime = self.runtime
        context.add_llm_tools(*(tool_cls() for tool_cls in ALL_TOOLS))
        if not self.runtime.admin_only and not self.runtime.allowed_users:
            logger.warning("[desktop_pilot] 已关闭仅管理员可用，所有用户都能通过 bot 操控这台电脑")

    async def terminate(self):
        if self.runtime is None:
            return
        from .tools import DesktopTool

        if DesktopTool.runtime is self.runtime:
            DesktopTool.runtime = None
        self.runtime.worker.shutdown()
