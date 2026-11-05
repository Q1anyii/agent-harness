"""context 管理测试：token 估算 / system prompt 构造 / 窗口裁剪四类边界。"""
from __future__ import annotations

from agent.context import build_system_prompt, estimate_tokens, trim_messages


# ---------- token 估算 ----------

def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0


def test_estimate_tokens_basic():
    assert estimate_tokens("你好") == 1  # 2 字符 // 2
    assert estimate_tokens("hello world") == 5  # 11 字符 // 2


# ---------- system prompt ----------

def test_build_system_prompt_contains_tools_and_time():
    prompt = build_system_prompt(["calculator", "weather"], now="2026-11-05T12:00:00+08:00")
    assert "calculator" in prompt and "weather" in prompt
    assert "2026-11-05T12:00:00" in prompt
    assert "工具" in prompt


def test_build_system_prompt_no_tools():
    prompt = build_system_prompt([])
    assert "（无）" in prompt


# ---------- 窗口裁剪：边界 ----------

def test_trim_empty():
    assert trim_messages([], 100) == []


def test_trim_only_system():
    msgs = [{"role": "system", "content": "sys"}]
    assert trim_messages(msgs, 100) == msgs


def test_trim_keeps_system_and_latest_user():
    """超窗时：system 保留 + 最近 user 无条件保留，中间的旧消息被裁掉。"""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "旧问题一" * 100},   # 300 字符 ≈ 150 token
        {"role": "assistant", "content": "旧回答一" * 100},
        {"role": "user", "content": "旧问题二" * 100},
        {"role": "assistant", "content": "旧回答二" * 100},
        {"role": "user", "content": "当前问题"},          # 4 字符 ≈ 2 token
    ]
    out = trim_messages(msgs, max_tokens=20)
    roles = [m["role"] for m in out]
    # system 与最后一条 user 必然在
    assert roles[0] == "system"
    assert out[-1]["content"] == "当前问题"
    # 旧消息被裁剪（总长应显著小于原列表）
    assert len(out) <= 3


def test_trim_keeps_as_much_recent_as_budget():
    """预算充足时全部保留，不误裁。"""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！"},
    ]
    out = trim_messages(msgs, max_tokens=1000)
    assert len(out) == 3


def test_trim_single_oversized_message_kept():
    """单条超长消息：当前问题无条件保留（不截断，MVP 约定），不崩溃。"""
    msgs = [{"role": "user", "content": "长" * 5000}]
    out = trim_messages(msgs, max_tokens=10)
    assert len(out) == 1
    assert out[0]["content"] == "长" * 5000
