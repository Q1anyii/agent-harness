"""日志存储与全局中间件测试（⑤）：内存/SQLite 双实现 + 计时兜底行为。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.log import LogRecord, MemoryLogStore, SQLiteLogStore
from agent.session import sqlite_transaction

# main 模块级实例（LOG_STORE 未设 → memory），中间件每次请求都会写入
import main as app_main


def test_memory_log_append_and_list_latest_first():
    store = MemoryLogStore()
    store.append(LogRecord(ts="t1", method="GET", path="/a", status=200, duration_ms=1.0))
    store.append(LogRecord(ts="t2", method="GET", path="/b", status=404, duration_ms=2.0))
    assert len(store.list()) == 2
    # list 最新在前：方便调用方取最近一条
    assert store.list()[0].path == "/b"
    assert store.list(limit=1)[0].status == 404


def test_sqlite_log_store_persist_and_query(tmp_path):
    db = tmp_path / "logs.db"
    store = SQLiteLogStore(str(db))
    store.append(
        LogRecord(
            ts="t1", method="POST", path="/api/sessions/abc/messages",
            session_id="abc", status=500, duration_ms=12.5, error="ValueError: boom",
        )
    )
    # 新实例（模拟重启后）仍能读回：证明真落库而非内存
    store2 = SQLiteLogStore(str(db))
    rows = store2.list()
    assert len(rows) == 1
    assert rows[0].status == 500
    assert rows[0].error == "ValueError: boom"
    assert rows[0].session_id == "abc"
    assert rows[0].duration_ms == 12.5


def test_sqlite_log_limit_desc_order(tmp_path):
    store = SQLiteLogStore(str(tmp_path / "logs.db"))
    for i in range(5):
        store.append(LogRecord(ts=f"t{i}", method="GET", path=f"/p{i}", status=200, duration_ms=float(i)))
    rows = store.list(limit=2)
    # ORDER BY id DESC + LIMIT：最新 2 条
    assert [r.path for r in rows] == ["/p4", "/p3"]


def test_session_id_extracted_from_path():
    assert app_main._session_id_from_path("/api/sessions/xyz/messages") == "xyz"
    assert app_main._session_id_from_path("/api/health") == ""
    assert app_main._session_id_from_path("/api/sessions") == ""


def test_middleware_records_normal_request(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    rec = app_main.log_store.list()[0]
    assert rec.method == "GET"
    assert rec.path == "/api/health"
    assert rec.status == 200
    assert rec.duration_ms >= 0
    assert rec.error == ""


def test_middleware_records_404():
    client = TestClient(app_main.app)
    resp = client.get("/api/sessions/no_such/messages")
    assert resp.status_code == 404
    rec = app_main.log_store.list()[0]
    assert rec.status == 404
    assert rec.session_id == "no_such"
    assert rec.error == ""


def test_middleware_500_on_unhandled_exception(monkeypatch):
    """未捕获异常：中间件兜底返回 500 JSON + 日志记录 error（不泄露堆栈细节）。"""
    async def boom(session, content):
        raise RuntimeError("内部炸了")

    monkeypatch.setattr(app_main.runtime, "async_run", boom)
    client = TestClient(app_main.app)
    sid = client.post("/api/sessions").json()["session_id"]
    resp = client.post(f"/api/sessions/{sid}/messages", json={"content": "hi"})
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"].startswith("服务器内部错误: RuntimeError")
    rec = app_main.log_store.list()[0]
    assert rec.status == 500
    assert rec.session_id == sid
    assert "RuntimeError" in rec.error


@pytest.fixture()
def client():
    return TestClient(app_main.app)
