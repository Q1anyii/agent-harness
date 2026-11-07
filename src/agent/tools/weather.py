"""天气查询工具（联网）：wttr.in 免费天气 API，无需 key。

架构说明：
- _fetch() 独立成模块级函数，便于测试 monkeypatch（保持离线确定性）；
  真实网络路径在 LLM_BACKEND=deepseek 联调时验证。
- 网络/解析失败一律兜底返回错误文案，不让工具级异常阻断 Agent 循环
  （对应需求分析「异常处理：网络处理、连接超时」）。
"""
from __future__ import annotations

import httpx

from agent.constants import HTTP_TIMEOUT_SECONDS

from .base import Tool, register

_TIMEOUT_SECONDS = HTTP_TIMEOUT_SECONDS


def _fetch(city: str) -> dict | None:
    """请求 wttr.in 并解析出当前天气字段；网络失败/超时/解析失败返回 None。"""
    try:
        resp = httpx.get(f"https://wttr.in/{city}?format=j1", timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        return data.get("current_condition", [{}])[0] or {}
    except (httpx.HTTPError, ValueError):
        return None


def run(city: str) -> str:
    # 1) 参数校验：空城市直接报错（Mock 路由也可能抽出空串）
    if city is None or not str(city).strip():
        return "错误：请指定要查询的城市"
    name = str(city).strip()

    # 2) 联网查询当前天气
    cond = _fetch(name)
    if cond is None:
        return f"天气查询（联网）：暂时无法获取「{name}」的天气（网络或服务异常），请稍后再试"

    # 3) 组装可读文本：优先中文描述（lang_zh），缺失时退回英文描述
    desc = ""
    lang_zh = cond.get("lang_zh") or []
    if lang_zh:
        desc = lang_zh[0].get("value", "")
    if not desc:
        desc = (cond.get("weatherDesc") or [{}])[0].get("value", "")
    temp = cond.get("temp_C", "?")
    humidity = cond.get("humidity", "?")
    winddir = cond.get("winddir16Point", "?")
    windspeed = cond.get("windspeedKmph", "?")
    return (
        f"天气查询（联网）：{name} {desc}，{temp}℃，"
        f"湿度 {humidity}%，{winddir}风 {windspeed} km/h"
    )


register(Tool(
    name="weather",
    description="查询城市实时天气（联网，数据源 wttr.in）。",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名，例如 北京、上海、赣州"},
        },
        "required": ["city"],
    },
    handler=run,
))
