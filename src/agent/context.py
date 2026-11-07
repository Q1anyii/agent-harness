"""上下文管理：system prompt 构造 + token 估算 + 窗口裁剪。

对应需求：context 有效管理（架构题模块一第二问——上下文膨胀）。
策略（MVP）：
- system prompt：会话开始时构造一次，运行时插入消息首条（LLM 无状态，每次携带）
- token 估算：粗算（中文约 1 字≈1 token，英文约 4 字符≈1 token，len//2 折中）；
  工具调用的函数名与 arguments 也计入，避免 assistant(tool_calls) 内容为空被估成零成本
- 窗口裁剪：按「消息组」裁剪——assistant(tool_calls) 与其后续 tool 结果共进退，
  避免切在工具链中间留下孤立 tool 消息（OpenAI 兼容 API 会 400）；
  system 与最新一组（当前提问）无条件保留
"""
from __future__ import annotations

from datetime import datetime, timezone

from agent.constants import CHARS_PER_TOKEN


def estimate_tokens(text: str | None) -> int:
    """粗略 token 估算（无分词器时的固定系数折算）。

    注意：这是 0.5 token/字符的固定折算，不是统计平均值——中文实际约 1 字 1 token
    （低估约一倍），英文约 4 字符 1 token（高估约一倍），误差靠 max_context_tokens
    的裕度吸收。
    """
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def build_system_prompt(tool_names: list[str], now: str | None = None) -> str:
    """构造会话级 system prompt：角色、能力边界、工具使用约定、当前时间。

    tool_names：可用工具名列表（决定 LLM 可调用范围）；
    now：当前时间（真实 LLM 无内置时钟，显式告知辅助时效判断）。
    """
    if now is None:
        now = datetime.now(timezone.utc).isoformat()
    tools = "、".join(tool_names) if tool_names else "（无）"
    return (
        "你是 agent-harness 的 AI 助手。\n"
        f"可用工具：{tools}。当用户请求需要实时数据或计算时，优先调用对应工具，"
        "不要凭空编造结果。\n"
        "调用工具后，根据工具返回结果组织最终回复；若工具执行失败，如实说明错误。\n"
        f"当前时间：{now}"
    )


def message_cost(message: dict) -> int:
    """单条消息的估算成本：content + 工具调用的函数名与 arguments。

    assistant 发起工具调用时 content 通常为空，只估 content 会把这轮估成 0 token，
    而 arguments（搜索词、todo 内容）可能有几十上百 token，必须一并计入。
    """
    cost = estimate_tokens(message.get("content"))
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        cost += estimate_tokens(fn.get("name"))
        cost += estimate_tokens(fn.get("arguments"))
    return cost


def group_messages(messages: list[dict]) -> list[list[dict]]:
    """把消息切分成组：assistant(tool_calls) + 紧随其后的连续 tool 消息为一组。

    其余消息（user、不带 tool_calls 的 assistant）各自成组。裁剪以组为单位，
    保证 tool_call 与 tool 结果同进同出，不会产生孤立 tool 消息。
    """
    groups: list[list[dict]] = []
    i = 0
    while i < len(messages):
        message = messages[i]
        if message.get("role") == "assistant" and message.get("tool_calls"):
            group = [message]
            i += 1
            while i < len(messages) and messages[i].get("role") == "tool":
                group.append(messages[i])
                i += 1
            groups.append(group)
        else:
            groups.append([message])
            i += 1
    return groups


def trim_messages(messages: list[dict], max_tokens: int) -> list[dict]:
    """context 窗口裁剪：保留 system + 最近消息，丢弃最旧消息直到不超窗。

    边界约定：
    - system 消息（role == "system"）无条件保留；
    - 最新一组（通常为当前 user 提问）无条件保留——即使超窗，至少保证能回答
      当前问题（超长单条不截断，MVP 可接受，后续可加摘要节点）；
    - 其余消息组从新到旧尝试保留，累计成本超过 max_tokens 即停止；
    - 工具调用与工具结果按组共进退，绝不切开工具链。
    """
    if not messages:
        return []
    system_msgs = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    if not rest:
        return system_msgs

    total = sum(message_cost(m) for m in system_msgs)
    kept_groups: list[list[dict]] = []
    # 从最新组往回保留：第一组（最新）无条件入列，之后按预算判断
    for group in reversed(group_messages(rest)):
        cost = sum(message_cost(m) for m in group)
        if not kept_groups or total + cost <= max_tokens:
            kept_groups.append(group)
            total += cost
        else:
            break
    kept_groups.reverse()
    kept = [m for group in kept_groups for m in group]
    return system_msgs + kept
