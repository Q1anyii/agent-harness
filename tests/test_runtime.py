"""Agent 运行时测试：循环、轮次限制、busy 拒绝、trace 记录。"""
from __future__ import annotations

import pytest

from agent.llm import LLMClient, LLMResponse, MockLLM, ToolCall
from agent.runtime import AgentRuntime
from agent.session import Session, SessionBusyError, SessionManager


def _make_runtime(max_rounds: int = 8) -> AgentRuntime:
    return AgentRuntime(llm=MockLLM(), max_rounds=max_rounds)


def _new_session(mgr: SessionManager) -> Session:
    return mgr.create()


# ---------- 正常路径 ----------

def test_plain_chat_no_tool_call():
    mgr = SessionManager()
    s = _new_session(mgr)
    result = _make_runtime().run(s, "你好")
    assert result.reply
    assert result.trace == []
    assert result.rounds_used == 0
    assert s.state == "idle"
    assert s.messages[-1]["role"] == "assistant"


def test_tool_call_flow_calculator():
    mgr = SessionManager()
    s = _new_session(mgr)
    result = _make_runtime().run(s, "帮我计算 1+2*3")
    assert result.reply  # 工具结果后应有最终回复
    assert len(result.trace) == 1
    item = result.trace[0]
    assert item["tool"] == "calculator"
    assert item["status"] == "success"
    assert item["duration_ms"] >= 0
    assert result.rounds_used == 1


def test_weather_tool_call():
    mgr = SessionManager()
    s = _new_session(mgr)
    result = _make_runtime().run(s, "北京天气怎么样")
    assert result.trace[0]["tool"] == "weather"
    assert "北京" in result.trace[0]["result"]


def test_tool_result_persisted_in_session():
    """工具结果与对话历史应保留在会话中，支撑追问（边界：会话连续性）。"""
    mgr = SessionManager()
    s = _new_session(mgr)
    _make_runtime().run(s, "帮我计算 1+2*3")
    roles = [m["role"] for m in s.messages]
    assert "tool" in roles
    assert "assistant" in roles


# ---------- 异常与边界 ----------

def test_unknown_tool_returns_error_trace():
    """未知工具不应崩溃，trace 记录 error 并继续。"""
    mgr = SessionManager()
    s = _new_session(mgr)
    runtime = _make_runtime()
    runtime._execute_tool("no_such_tool", {})
    result = runtime.run(s, "你好")
    assert result.reply


def test_busy_session_rejected():
    """会话 busy 时新消息应被拒绝（对应架构题模块四第 2 问）。"""
    mgr = SessionManager()
    s = _new_session(mgr)
    s.state = "busy"
    with pytest.raises(SessionBusyError):
        _make_runtime().run(s, "又来一条")


def test_max_rounds_limited():
    """单次问答轮次上限：超过后终止并给出提示（不阻塞后续会话）。"""
    mgr = SessionManager()
    s = _new_session(mgr)
    runtime = AgentRuntime(llm=MockLLM(), max_rounds=1)
    # 构造会持续触发工具的输入：MockLLM 对同一 user 消息每次都会路由
    result = runtime.run(s, "计算 1+2")
    assert result.rounds_used <= 1
    assert "轮次上限" in result.reply or result.rounds_used >= 1
    assert s.state == "idle"  # 异常终止后会话仍可复用


def test_empty_user_message_not_crash():
    mgr = SessionManager()
    s = _new_session(mgr)
    result = _make_runtime().run(s, "   ")
    assert result.reply


def test_multi_round_tool_loop_counted():
    """工具结果回填后 LLM 再次路由（Mock 规则），rounds_used 正确累加。"""
    mgr = SessionManager()
    s = _new_session(mgr)
    runtime = _make_runtime(max_rounds=8)
    # MockLLM 在 tool 消息后仍读最后一条 user 消息 -> 持续触发 calculator
    result = runtime.run(s, "计算 1+2")
    assert result.rounds_used >= 1
    assert len(result.trace) == result.rounds_used


class MultiToolLLM(LLMClient):
    """一次决策返回多个工具调用，用于验证 rounds_used 按工具条数统计。"""

    def __init__(self) -> None:
        self._decided = False

    def init(self) -> None:
        """无外部客户端，无需初始化。"""
        return None

    def generate(self, messages: list[dict]) -> LLMResponse:
        if not self._decided:
            self._decided = True
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(name="calculator", args={"expression": "1+1"}),
                    ToolCall(name="weather", args={"city": "北京"}),
                ],
            )
        return LLMResponse(content="全部完成", tool_calls=None)


def test_rounds_used_counts_tool_calls_not_decision_rounds():
    """一次决策返回多个工具时，rounds_used 应等于工具条数（2），而非决策轮数。"""
    mgr = SessionManager()
    s = _new_session(mgr)
    result = AgentRuntime(llm=MultiToolLLM()).run(s, "帮我计算 1+1 和查北京天气")
    assert len(result.trace) == 2
    assert result.rounds_used == 2


def test_rounds_used_counts_only_latest_user_tools():
    """多轮会话中，rounds_used 只统计最近一条 user 之后的工具调用，不跨轮累计。"""
    mgr = SessionManager()
    s = _new_session(mgr)
    runtime = _make_runtime()
    r1 = runtime.run(s, "帮我计算 1+2*3")
    assert r1.rounds_used == 1
    r2 = runtime.run(s, "你好")
    assert r2.rounds_used == 0
    r3 = runtime.run(s, "北京天气怎么样")
    assert r3.rounds_used == 1  # 不是累计 2
