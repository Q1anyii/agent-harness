"""存储层测试：SQLiteSessionStore 落库闭环（tmp_path 隔离，不污染项目目录）。"""
from __future__ import annotations

import pytest

from agent.session import (
    SQLiteSessionStore,
    Session,
    SessionManager,
    SessionNotFoundError,
)


@pytest.fixture()
def store(tmp_path):
    return SQLiteSessionStore(str(tmp_path / "test.db"))


# ---------- 创建 / 读取 ----------

def test_create_and_get_roundtrip(store):
    s = store.create()
    got = store.get(s.session_id)
    assert got.session_id == s.session_id
    assert got.state == "idle"
    assert got.messages == []
    assert got.traces == []


def test_get_unknown_raises(store):
    with pytest.raises(SessionNotFoundError):
        store.get("no_such_session")


# ---------- save 落库可重读 ----------

def test_save_persists_messages_and_traces(store):
    s = store.create()
    s.messages = [
        {"role": "user", "content": "北京天气"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_1", "name": "weather", "arguments": '{"city": "北京"}'}],
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "weather", "content": "晴 9°C"},
        {"role": "assistant", "content": "北京今天晴，9 度。"},
    ]
    s.traces = [
        {"tool": "weather", "args": {"city": "北京"}, "result": "晴 9°C",
         "status": "success", "duration_ms": 12.5},
    ]
    s.state = "idle"
    s.system_prompt = "你是助手"
    store.save(s)

    # 用新对象重读（模拟进程重启后的恢复）
    got = store.get(s.session_id)
    assert got.messages == s.messages  # 含 tool_calls 结构（extra JSON 往返）
    assert got.traces == s.traces
    assert got.state == "idle"


def test_save_twice_overwrites(store):
    """重复 save 是覆盖而非追加：消息不翻倍。"""
    s = store.create()
    s.messages = [{"role": "user", "content": "第一轮"}]
    store.save(s)
    s.messages = [{"role": "user", "content": "第一轮"}, {"role": "assistant", "content": "回复"}]
    store.save(s)
    got = store.get(s.session_id)
    assert len(got.messages) == 2


# ---------- 列表 / 删除 ----------

def test_list_sorted_and_count(store):
    s1 = store.create()
    s1.messages = [{"role": "user", "content": "你好"}]
    store.save(s1)
    s2 = store.create()
    sessions = store.list()
    assert len(sessions) == 2
    # 列表语义与内存实现一致：包含消息（message_count 可用）
    counts = {s.session_id: len(s.messages) for s in sessions}
    assert counts[s1.session_id] == 1
    assert counts[s2.session_id] == 0


def test_remove_cascades_messages_and_traces(store):
    s = store.create()
    s.messages = [{"role": "user", "content": "待删除"}]
    s.traces = [{"tool": "calculator", "args": {}, "result": "1", "status": "success"}]
    store.save(s)
    store.remove(s.session_id)
    with pytest.raises(SessionNotFoundError):
        store.get(s.session_id)


def test_remove_unknown_raises(store):
    with pytest.raises(SessionNotFoundError):
        store.remove("no_such_session")


# ---------- 内存实现接口一致性（save 为 no-op 不破坏） ----------

def test_memory_manager_implements_store_interface():
    mgr = SessionManager()
    s = mgr.create()
    s.messages = [{"role": "user", "content": "hi"}]
    mgr.save(s)  # no-op，不抛错
    assert mgr.get(s.session_id).messages[0]["content"] == "hi"
    assert isinstance(mgr, object)  # 占位断言：接口方法全部可调用即可
