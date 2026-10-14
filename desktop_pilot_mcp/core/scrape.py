"""抓取网页并转成 Markdown 文本，比截图省 token。请求从被操控的电脑发出，使用这台电脑的网络。"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_NOISE_TAGS = ["script", "style", "noscript", "svg", "iframe", "template", "canvas", "form"]


def _html_to_markdown(content: bytes) -> tuple[str, str]:
    # 交给 BeautifulSoup 按 meta 标签识别编码，兼容 GBK 等老网页
    soup = BeautifulSoup(content, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    for tag in soup(_NOISE_TAGS):
        tag.decompose()
    body = soup.find("main") or soup.find("article") or soup.body or soup
    text = markdownify(str(body), heading_style="ATX", strip=["img"])
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return title, text


async def scrape(url: str, offset: int, limit: int) -> str:
    url = url.strip()
    if not url:
        raise ValueError("请提供网址")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20, headers=_HEADERS) as client:
            resp = await client.get(url)
    except httpx.HTTPError as e:
        raise OSError(f"访问 {url} 失败：{type(e).__name__} {e}") from e

    ctype = resp.headers.get("content-type", "").lower()
    title = ""
    if "html" in ctype or (not ctype and resp.content.lstrip()[:1] == b"<"):
        title, text = _html_to_markdown(resp.content)
    elif ctype.startswith("text/") or "json" in ctype or "xml" in ctype:
        text = resp.text
    else:
        return f"{resp.url} 返回的是非文本内容（{ctype or '未知类型'}，{len(resp.content)} 字节），无法转成文字"

    offset = max(0, offset)
    chunk = text[offset : offset + limit]
    header = f"网址：{resp.url}（HTTP {resp.status_code}）"
    if title:
        header += f"\n标题：{title}"
    end = offset + len(chunk)
    header += f"\n正文共 {len(text)} 字符，当前显示第 {offset}~{end} 字符"
    if end < len(text):
        header += f"，可用 offset={end} 继续读取"
    return f"{header}\n\n{chunk}"
