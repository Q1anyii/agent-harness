"""工具路由：判断用户 query 是否需要调用工具，并做最小参数提取（Mock 路由）。"""
from __future__ import annotations

import re

# 工具名 -> 触发词列表（命中任一触发词即路由到该工具）
_TOOL_TRIGGERS: dict[str, list[str]] = {
    "calculator": ["计算", "算一下", "等于多少", "算算", "calculator", "算一算", "算下"],
    "search": ["搜索", "查一下", "搜一下", "查找", "介绍一下", "search", "是什么", "什么是"],
    "weather": ["天气", "气温", "多少度", "下雨", "weather", "温度"],
    "todo": ["待办", "todo", "提醒我", "记一下", "待办事项", "to-do"],
}

_STRIP_PATTERNS: list[str] = [
    "天气怎么样", "天气如何", "气温怎么样", "温度怎么样", "天气", "气温", "多少度", "下雨吗", "呢", "怎么样", "如何", "怎么样啊", "是什么", "什么是", "介绍一下",
]


def route(query: str) -> str | None:
    """返回命中的工具名；不命中返回 None。"""
    if query is None or not str(query).strip():
        return None
    text = str(query).strip().lower()
    for tool_name, triggers in _TOOL_TRIGGERS.items():
        for trigger in triggers:
            if trigger.lower() in text:
                return tool_name
    return None


def _strip_noise(text: str, tool_name: str) -> str:
    """去掉触发词与常见语气词，尽量保留有效参数（Mock 最小实现）。"""
    cleaned = text
    for pattern in _STRIP_PATTERNS:
        cleaned = cleaned.replace(pattern, "")
    # 去掉所有触发词
    for trigger in _TOOL_TRIGGERS.get(tool_name, []):
        cleaned = cleaned.replace(trigger, "")
    return cleaned.strip(" ，,。！？!?：:；;")


def extract_args(tool_name: str, query: str) -> dict[str, str]:
    """从 query 中提取工具参数（Mock 最小实现）。

    - calculator: 提取表达式（数字与运算符组成的子串）
    - search: 去噪后的剩余文本作为关键词
    - weather: 去噪后的剩余文本作为城市名
    """
    text = str(query).strip() if query else ""
    if tool_name == "calculator":
        match = re.search(r"[0-9+\-*/%().\s]{1,80}", text)
        expr = match.group(0).strip() if match else ""
        return {"expression": expr}
    if tool_name == "search":
        return {"query": _strip_noise(text, tool_name) or text}
    if tool_name == "weather":
        city = _strip_noise(text, tool_name)
        # 常见城市限定 2~4 个中文字符，超出则整体截断到 6 字
        city = city[:6] if len(city) <= 6 else city[:6]
        return {"city": city or text}
    if tool_name == "todo":
        # 按语气词判断动作：添加/完成 关键词在前，其余视为查看
        cleaned = _strip_noise(text, tool_name)
        if any(k in cleaned for k in ("添加", "新增", "记下", "记录", "加个")):
            for k in ("添加", "新增", "记下", "记录", "加个", "：", ":"):
                cleaned = cleaned.replace(k, "")
            return {"action": "add", "text": cleaned.strip(" ，")}
        if any(k in cleaned for k in ("完成", "搞定", "勾掉", "打个勾")):
            for k in ("完成", "搞定", "勾掉", "打个勾", "：", ":"):
                cleaned = cleaned.replace(k, "")
            return {"action": "done", "text": cleaned.strip(" ，")}
        return {"action": "list", "text": cleaned}
    return {}
