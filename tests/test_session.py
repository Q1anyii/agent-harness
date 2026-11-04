"""会话管理测试：创建/查询/列表/隔离。"""
from __future__ import annotations

import pytest

from agent.session import SessionManager, SessionNotFoundError


def test_create_session():
    mgr = SessionManager()
    s = mgr.create()
    assert s.session_id
    assert s.state == "idle"
    assert s.messages == []


def test_get_existing_and_missing():
    mgr = SessionManager()
    s = mgr.create()
    assert mgr.get(s.session_id) is s
    with pytest.raises(SessionNotFoundError):
        mgr.get("no_such_id")


def test_list_orders_by_created_desc():
    mgr = SessionManager()
    a = mgr.create()
    b = mgr.create()
    ids = [s.session_id for s in mgr.list()]
    assert ids == [b.session_id, a.session_id]


def test_session_isolation():
    """会话隔离：A 会话的消息不会串到 B 会话（核心边界）。"""
    mgr = SessionManager()
    a = mgr.create()
    b = mgr.create()
    a.messages.append({"role": "user", "content": "只属于 A"})
    assert len(b.messages) == 0
    assert b.messages != a.messages


def test_append_trace():
    mgr = SessionManager()
    s = mgr.create()
    mgr.append_trace(s, [{"tool": "calculator", "result": "ok"}])
    assert len(s.traces) == 1
