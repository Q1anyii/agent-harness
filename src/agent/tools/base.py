"""工具注册表与统一接口。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class Tool:
    """一个可被 Agent 调用的工具。

    parameters 使用 JSON Schema 描述入参，供路由/前端/契约使用。
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[str]]


TOOL_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    if tool.name in TOOL_REGISTRY:
        raise ValueError(f"工具名重复注册: {tool.name}")
    TOOL_REGISTRY[tool.name] = tool


def get_tool(name: str) -> Tool | None:
    return TOOL_REGISTRY.get(name)


def get_all_tools() -> list[Tool]:
    return list(TOOL_REGISTRY.values())
