"""搜索工具（联网）：DuckDuckGo HTML 版 + BeautifulSoup 解析搜索结果，无需 key。

架构说明：
- _fetch() 独立成模块级函数，便于测试 monkeypatch（保持离线确定性）。
- 网络/解析失败一律兜底返回错误文案，不让工具级异常阻断 Agent 循环。
"""
from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from agent.constants import HTTP_TIMEOUT_SECONDS, SEARCH_MAX_RESULTS

from .base import Tool, register

_TIMEOUT_SECONDS = HTTP_TIMEOUT_SECONDS
_MAX_RESULTS = SEARCH_MAX_RESULTS


def _fetch(query: str) -> list[dict] | None:
    """抓取 DuckDuckGo HTML 搜索结果，解析出 标题/摘要；失败/超时返回 None。"""
    try:
        resp = httpx.get(
            f"https://html.duckduckgo.com/html/?q={query}",
            timeout=_TIMEOUT_SECONDS,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        return None

    # 用 BeautifulSoup 解析：.result__a 是结果标题（含链接），.result__snippet 是摘要
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for link in soup.select(".result__a")[:_MAX_RESULTS]:
        title = link.get_text(" ", strip=True)
        snippet_el = link.find_next(class_="result__snippet")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        results.append({"title": title, "snippet": snippet})
    return results or None


def run(query: str) -> str:
    # 1) 参数校验：空关键词直接报错
    if query is None or not str(query).strip():
        return "错误：搜索关键词为空"
    text = str(query).strip()

    # 2) 联网搜索：空列表或 None 都视为无结果
    results = _fetch(text)
    if not results:
        return f"搜索结果（联网）：未找到与「{text}」相关的内容，或网络暂时不可用"

    # 3) 组装文本：最多展示前 N 条 标题+摘要
    lines = [f"搜索结果（联网）：「{text}」"]
    for i, r in enumerate(results, 1):
        line = f"{i}. {r['title']}"
        if r["snippet"]:
            line += f" —— {r['snippet']}"
        lines.append(line)
    return "\n".join(lines)


register(Tool(
    name="search",
    description="联网搜索（数据源 DuckDuckGo），返回相关网页标题与摘要。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词，例如 agent、langgraph"},
        },
        "required": ["query"],
    },
    handler=run,
))
