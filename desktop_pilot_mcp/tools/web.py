"""网页抓取工具。"""

from typing import Annotated

from pydantic import Field

from ..config import ToolsConfig
from ..core import scrape
from .common import Content, Registrar, guarded, text


def register(reg: Registrar, tools_cfg: ToolsConfig) -> None:
    if not tools_cfg.enabled["scrape"]:
        return

    @reg.tool("scrape", "从这台电脑访问网址，把网页正文转成 Markdown 文本返回。只需要阅读网页内容时比截图更快、更省 token；"
                        "需要登录或由脚本动态加载的页面可能抓不全，此时改用浏览器加截图。", read_only=True)
    async def scrape_url(
        url: Annotated[str, Field(description="网址，可以省略 https://")],
        offset: Annotated[int, Field(description="从正文第几个字符开始返回，用于继续阅读长网页")] = 0,
    ) -> Content:
        return text(await guarded(scrape.scrape(url, offset, tools_cfg.output_limit)))
