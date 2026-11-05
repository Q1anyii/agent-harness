"""流式事件测试：EventQueue 抽象（队列单元 + runtime 事件集成 + API 轮询端点）。"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from agent.events import InMemoryQueue
from agent.llm import MockLLM
from agent.runtime import AgentRuntime
from agent.session import SessionManager
from main import app, manager, runtime as api_runtime

client = TestClient(app)


# ---------- InMemoryQueue 单元测试 ----------

def test_publish_subscribe_incremental():
    q = InMemoryQueue()
    q.publish("s1", {"type": "reasoning", "content": "a"})
    q.publish("s1", {"type": "reasoning", "content": "b"})
    q.publish("s1", {"type": "message_delta", "delta": "c", "done": True})
    # 全量（since=0）
    all_evts = q.subscribe("s1", 0)
    assert [e["seq"] for e in all_evts] == [1, 2, 3]
    # 增量（since=2）
    inc = q.subscribe("s1", 2)
    assert [e["seq"] for e in inc] == [3]
    assert inc[0]["type"] == "message_delta"
    assert q.latest_seq("s1") == 3


def test_session_isolation():
    q = InMemoryQueue()
    q.publish("s1", {"type": "reasoning", "content": "a"})
    q.publish("s2", {"type": "message_delta", "delta": "b", "done": True})
    assert q.latest_seq("s1") == 1
    assert q.latest_seq("s2") == 1
    # 互不串扰：s1 拉不到 s2 的事件
    assert [e["type"] for e in q.subscribe("s1", 0)] == ["reasoning"]


def test_clear_removes_session_events():
    q = InMemoryQueue()
    q.publish("s1", {"type": "reasoning", "content": "a"})
    q.clear("s1")
    assert q.subscribe("s1", 0) == []
    assert q.latest_seq("s1") == 0
    # clear 后仍可继续 publish（seq 重新计数）
    q.publish("s1", {"type": "message_delta", "delta": "b", "done": True})
    assert [e["seq"] for e in q.subscribe("s1", 0)] == [1]


def test_window_caps_old_events():
    q = InMemoryQueue(max_per_session=3)
    for i in range(5):
        q.publish("s1", {"type": "reasoning", "content": str(i)})
    evts = q.subscribe("s1", 0)
    # 只保留最近 3 条，seq 单调不重置
    assert [e["seq"] for e in evts] == [3, 4, 5]
    assert q.latest_seq("s1") == 5


def test_unknown_session_subscribe_empty():
    q = InMemoryQueue()
    assert q.subscribe("ghost", 0) == []
    assert q.latest_seq("ghost") == 0


# ---------- runtime 事件集成 ----------

def test_runtime_pushes_event_sequence():
    """工具问答：事件顺序 = reasoning → tool_call → tool_result → reasoning → message_delta(done)。"""
    q = InMemoryQueue()
    rt = AgentRuntime(llm=MockLLM(), max_rounds=8, queue=q)
    mgr = SessionManager()
    s = mgr.create()

    result = rt.run(s, "帮我计算 1+2*3")
    assert result.reply

    events = q.subscribe(s.session_id, 0)
    types = [e["type"] for e in events]
    assert "reasoning" in types
    assert "tool_call" in types and "tool_result" in types
    assert "message_delta" in types
    assert types[-1] == "message_delta"

    # tool_call 与 tool_result 同 id 配对（订单号）
    call = next(e for e in events if e["type"] == "tool_call")
    res = next(e for e in events if e["type"] == "tool_result")
    assert call["id"] == res["id"]
    assert call["name"] == "calculator"
    assert res["status"] == "success"

    # 消息增量连续拼接 = 完整回复，最后一块 done=True
    deltas = [e for e in events if e["type"] == "message_delta"]
    assert deltas[-1]["done"] is True
    assert "".join(e["delta"] for e in deltas) == result.reply


def test_reasoning_persisted_in_messages():
    """⑥ 落库：决策消息与最终回复消息都带 reasoning，全量刷新后思考过程不丢。"""
    rt = AgentRuntime(llm=MockLLM(), max_rounds=8)
    mgr = SessionManager()
    s = mgr.create()

    rt.run(s, "帮我计算 1+2*3")
    # 历史中找决策消息（assistant 带 tool_calls）与总结消息（assistant 带 content）
    decision = next(m for m in s.messages if m.get("tool_calls"))
    summary = next(m for m in s.messages if m.get("role") == "assistant" and not m.get("tool_calls"))
    assert decision["reasoning"]  # 决策前思考已落库
    assert "calculator" in decision["reasoning"]
    assert summary["reasoning"]  # 总结前思考已落库
    assert "组织最终回复" in summary["reasoning"]


def test_runtime_no_queue_no_crash():
    """不传队列时（既有 sync 测试路径）静默跳过，不抛错。"""
    rt = AgentRuntime(llm=MockLLM())
    mgr = SessionManager()
    s = mgr.create()
    result = rt.run(s, "你好")
    assert result.reply


def test_async_runtime_pushes_events():
    async def _run():
        q = InMemoryQueue()
        rt = AgentRuntime(llm=MockLLM(), max_rounds=8, queue=q)
        mgr = SessionManager()
        s = mgr.create()
        result = await rt.async_run(s, "北京天气怎么样")
        return q, s.session_id, result

    q, sid, result = asyncio.run(_run())
    types = [e["type"] for e in q.subscribe(sid, 0)]
    assert "tool_call" in types and "tool_result" in types
    assert types[0] == "reasoning"  # 首个事件是思考过程


# ---------- API 轮询端点 ----------

def test_events_endpoint_returns_increments():
    sid = client.post("/api/sessions").json()["session_id"]
    client.post(f"/api/sessions/{sid}/messages", json={"content": "帮我计算 1+2*3"})

    r = client.get(f"/api/sessions/{sid}/events?since=0")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == sid
    types = [e["type"] for e in body["events"]]
    assert "tool_call" in types and "message_delta" in types
    latest = body["latest_seq"]

    # 增量续拉：since=latest 后无新事件
    r2 = client.get(f"/api/sessions/{sid}/events?since={latest}")
    assert r2.json()["events"] == []


def test_events_endpoint_unknown_session_404():
    r = client.get("/api/sessions/nope/events")
    assert r.status_code == 404


def test_delete_session_clears_events():
    sid = client.post("/api/sessions").json()["session_id"]
    client.post(f"/api/sessions/{sid}/messages", json={"content": "你好"})
    assert client.get(f"/api/sessions/{sid}/events?since=0").json()["latest_seq"] > 0
    client.delete(f"/api/sessions/{sid}")
    # 会话已删 → 404；事件随会话清理
    assert client.get(f"/api/sessions/{sid}/events?since=0").status_code == 404
