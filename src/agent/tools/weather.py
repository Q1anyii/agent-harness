"""天气查询工具（mock）：返回预设城市天气。"""
from __future__ import annotations

from .base import Tool, register

_MOCK_WEATHER: dict[str, str] = {
    "北京": "晴，24℃，东南风 2 级",
    "上海": "多云，26℃，东风 3 级",
    "广州": "雷阵雨，29℃，南风 2 级",
    "深圳": "阵雨，28℃，西南风 3 级",
    "杭州": "阴，22℃，东北风 2 级",
    "南昌": "多云，23℃，北风 2 级",
    "赣州": "晴转多云，25℃，北风 1 级",
}

_SUPPORTED = "、".join(_MOCK_WEATHER)


def run(city: str) -> str:
    if city is None or not str(city).strip():
        return "错误：请指定要查询的城市"
    name = str(city).strip()
    info = _MOCK_WEATHER.get(name)
    if info is None:
        return f"天气查询（mock）：暂未收录「{name}」，支持城市：{_SUPPORTED}。"
    return f"天气查询（mock）：{name} {info}"


register(Tool(
    name="weather",
    description="查询城市天气（mock 数据）。",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名，例如 北京、上海、赣州"},
        },
        "required": ["city"],
    },
    handler=run,
))
