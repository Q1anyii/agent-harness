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


# ---------- 窗口裁剪：工具链成组 ----------

def _has_orphan_tool(messages: list[dict]) -> bool:
    """输出中是否存在找不到对应 tool_calls 的 tool 消息（会触发 API 400）。"""
    call_ids = set()
    for m in messages:
        if m.get("role") == "assistant":
            for call in m.get("tool_calls") or []:
                call_ids.add(call.get("id"))
        elif m.get("role") == "tool" and m.get("tool_call_id") not in call_ids:
            return True
    return False


def _tool_group(call_id: str, arguments: str, result: str) -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "weather", "arguments": arguments},
                }
            ],
        },
        {"role": "tool", "tool_call_id": call_id, "content": result},
    ]


def test_trim_keeps_tool_group_atomic():
    """预算卡在工具组中间时整组丢弃，不产生孤立 tool 消息。"""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "查天气"},
        *_tool_group("c1", '{"city":"南昌"}', "晴 20 度"),
        {"role": "assistant", "content": "南昌今天晴，20 度"},
        {"role": "user", "content": "那北京呢"},
    ]
    out = trim_messages(msgs, max_tokens=10)
    assert out[0]["role"] == "system"
    assert out[-1]["content"] == "那北京呢"
    assert not _has_orphan_tool(out)
    assert not any(m.get("role") == "tool" for m in out)


def test_trim_counts_tool_arguments():
    """tool_calls 的 arguments 计入成本：参数长时整组被裁，参数短时保留。"""
    short = [
        {"role": "system", "content": "s"},
        *_tool_group("c1", "{}", "结果"),
        {"role": "user", "content": "问题"},
    ]
    long = [
        {"role": "system", "content": "s"},
        *_tool_group("c1", '{"q":"' + "长" * 200 + '"}', "结果"),
        {"role": "user", "content": "问题"},
    ]
    out_short = trim_messages(short, max_tokens=20)
    out_long = trim_messages(long, max_tokens=20)
    assert any(m.get("role") == "tool" for m in out_short)
    assert not any(m.get("role") == "tool" for m in out_long)
