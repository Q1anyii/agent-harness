"""搜索工具（mock）：基于内置知识库的关键词检索。"""
from __future__ import annotations

from .base import Tool, register

_MOCK_KB: dict[str, str] = {
    "agent": "Agent 是由大模型驱动、能自主调用工具完成任务的系统，核心是「感知-决策-行动」循环。",
    "rag": "RAG（检索增强生成）通过向量检索召回相关知识片段拼入提示词，缓解幻觉与知识时效问题。",
    "mitta": "Mitta 是作者自研的 AI 智能助理项目，采用 LangGraph + RAG + Agent 架构。",
    "langgraph": "LangGraph 以图结构组织 Agent 的节点与状态，支持循环、分支与人工介入。",
    "mem0": "Mem0 是长期记忆框架，用向量库存储用户事实，在生成前做记忆召回。",
    "python": "Python 是 agent-harness 项目的实现语言，理由：简单且作者最熟悉。",
    "fastapi": "FastAPI 是 agent-harness 的 Web 层框架，提供会话、消息与 trace 等 HTTP API。",
    "context": "上下文管理包含：单次问答工具轮次上限、短期记忆窗口、context 压缩（截断或摘要）。",
}

_SUPPORTED = "、".join(sorted(_MOCK_KB))


def run(query: str) -> str:
    if query is None or not str(query).strip():
        return "错误：搜索关键词为空"
    text = str(query).strip().lower()
    for keyword, answer in _MOCK_KB.items():
        if keyword in text:
            return f"搜索结果（mock）：{answer}"
    return f"搜索结果（mock）：未找到与「{query}」直接相关的内容，试试关键词：{_SUPPORTED}。"


register(Tool(
    name="search",
    description="搜索内置知识库（mock），返回与关键词相关的内容。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词，例如 agent、rag、fastapi"},
        },
        "required": ["query"],
    },
    handler=run,
))
