"""上下文管理：system prompt 构造 + token 估算 + 窗口裁剪。

对应需求：context 有效管理（架构题模块一第二问——上下文膨胀）。
策略（MVP）：
- system prompt：会话开始时构造一次，运行时插入消息首条（LLM 无状态，每次携带）
- token 估算：粗算（中文约 1 字≈1 token，英文约 4 字符≈1 token，len//2 折中）
- 窗口裁剪：保留 system + 最近消息，从最旧开始丢弃直到不超窗；
  最后一条 user（当前问题）无条件保留，保证能回答当前提问
"""
from __future__ import annotations

from datetime import datetime, timezone


def estimate_tokens(text: str) -> int:
    """粗略 token 估算（无分词器时的保守折中）。"""
    if not text:
        return 0
    # 中文/日文等 CJK 字符约 1 字 ≈ 1 token；英文约 4 字符 ≈ 1 token。
    # 简单折中：字符数 // 2 偏保守（宁可多估，避免超窗）。
    return max(1, len(text) // 2)


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


def trim_messages(messages: list[dict], max_tokens: int) -> list[dict]:
    """context 窗口裁剪：保留 system + 最近消息，丢弃最旧消息直到不超窗。

    边界约定：
    - system 消息（role == "system"）无条件保留；
    - 最后一条消息（通常为当前 user 提问）无条件保留——即使单条超窗，
      至少保证能回答当前问题（超长单条不截断，MVP 可接受，后续可加摘要节点）；
    - 其余消息从最旧到最新尝试保留，累计 token 超过 max_tokens 即停止。
    """
    if not messages:
        return []
    system_msgs = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    if not rest:
        return system_msgs

    kept: list[dict] = []
    total = sum(estimate_tokens(str(m.get("content", ""))) for m in system_msgs)
    # 从最新往回保留：第一条（最新）无条件入列，之后按预算判断
    for m in reversed(rest):
        cost = estimate_tokens(str(m.get("content", "")))
        if not kept or total + cost <= max_tokens:
            kept.append(m)
            total += cost
        else:
            break
    kept.reverse()
    return system_msgs + kept
