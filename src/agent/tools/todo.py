"""待办工具（todo）：进程内内存存储的 add/list/done。

存储取舍：模块级全局列表，进程内共享（与 session 同为内存实现；
需求分析「长期记忆」方向留待落库后按用户/会话维度隔离）。
"""
from __future__ import annotations

from .base import Tool, register

# 内存待办表：每条 {"id": 序号, "text": 内容, "done": 是否完成}
_TODOS: list[dict] = []
_NEXT_ID = 1


def _format_list(todos: list[dict]) -> str:
    """把待办列表拼成可读文本：未完成在前。"""
    if not todos:
        return "当前没有待办事项。"
    lines = ["当前待办："]
    for t in sorted(todos, key=lambda x: (x["done"], x["id"])):
        mark = "[x]" if t["done"] else "[ ]"
        lines.append(f"  {mark} #{t['id']} {t['text']}")
    return "\n".join(lines)


async def run(action: str, text: str | None = None) -> str:
    # 1) 参数校验：action 必填且只能是指定三种
    if action is None or str(action).strip() not in {"add", "list", "done"}:
        return "错误：action 必须是 add / list / done 之一"
    act = str(action).strip()

    # 2) list：直接返回当前列表
    if act == "list":
        return _format_list(_TODOS)

    content = str(text).strip() if text else ""
    if act == "add":
        # 3a) add：内容为空则报错，否则追加一条未完成待办
        if not content:
            return "错误：添加待办需要提供内容（text）"
        global _NEXT_ID
        _TODOS.append({"id": _NEXT_ID, "text": content, "done": False})
        _NEXT_ID += 1
        return f"已添加待办：{content}\n\n{_format_list(_TODOS)}"

    # 3b) done：按编号（数字）或原文本匹配，标记为已完成
    if not content:
        return "错误：完成待办需要提供编号或内容（text）"
    target = None
    for t in _TODOS:
        if content.isdigit():
            match = t["id"] == int(content)
        else:
            match = t["text"] == content
        if match:
            target = t
            break
    if target is None:
        return f"错误：找不到待办「{content}」"
    target["done"] = True
    return f"已完成待办：{target['text']}\n\n{_format_list(_TODOS)}"


register(Tool(
    name="todo",
    description="待办事项管理：添加（add）、查看（list）、完成（done）。",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "list", "done"],
                "description": "操作：添加 / 查看 / 完成",
            },
            "text": {
                "type": "string",
                "description": "待办内容（add 必填；done 填编号或原文本）",
            },
        },
        "required": ["action"],
    },
    handler=run,
))
