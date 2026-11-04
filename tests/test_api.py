"""API 层测试：健康/会话/消息/工具/trace/异常/边界 + api.json 契约校验。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app, manager, runtime

client = TestClient(app)

API_JSON = Path(__file__).resolve().parent.parent / "api.json"


# ---------- 系统 ----------

def test_health_ok():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------- 会话 ----------

def test_create_session_201():
    r = client.post("/api/sessions")
    assert r.status_code == 201
    body = r.json()
    assert body["session_id"]
    assert body["state"] == "idle"
    assert body["message_count"] == 0


def test_list_sessions():
    client.post("/api/sessions")
    r = client.get("/api/sessions")
    assert r.status_code == 200
    assert isinstance(r.json()["sessions"], list)


def test_list_sessions_auto_creates_default():
    """会话列表为空时，GET 自动新建一个默认会话（打开前端即可用）。"""
    for s in manager.list():
        manager.remove(s.session_id)
    r = client.get("/api/sessions")
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["message_count"] == 0


def test_delete_session_204_and_removed():
    """删除会话：204 且目标随即不可访问。"""
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 204
    r2 = client.get(f"/api/sessions/{sid}/messages")
    assert r2.status_code == 404


def test_delete_unknown_session_404():
    r = client.delete("/api/sessions/no_such_id")
    assert r.status_code == 404


# ---------- 消息（正常路径） ----------

def test_send_plain_message():
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post(f"/api/sessions/{sid}/messages", json={"content": "你好"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"]
    assert body["trace"] == []
    assert body["rounds_used"] == 0


def test_send_tool_message_calculator():
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post(f"/api/sessions/{sid}/messages", json={"content": "帮我计算 1+2*3"})
    assert r.status_code == 200
    body = r.json()
    assert body["rounds_used"] == 1
    assert len(body["trace"]) == 1
    item = body["trace"][0]
    assert item["tool"] == "calculator"
    assert item["status"] == "success"
    assert "7.0" in item["result"]
    assert item["duration_ms"] >= 0


def test_send_tool_message_weather():
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post(f"/api/sessions/{sid}/messages", json={"content": "北京天气怎么样"})
    body = r.json()
    assert body["trace"][0]["tool"] == "weather"


# ---------- 历史与 trace ----------

def test_messages_history_persists():
    sid = client.post("/api/sessions").json()["session_id"]
    client.post(f"/api/sessions/{sid}/messages", json={"content": "帮我计算 1+2*3"})
    r = client.get(f"/api/sessions/{sid}/messages")
    assert r.status_code == 200
    roles = [m["role"] for m in r.json()["messages"]]
    assert "user" in roles and "assistant" in roles and "tool" in roles


def test_trace_endpoint_returns_trace():
    sid = client.post("/api/sessions").json()["session_id"]
    client.post(f"/api/sessions/{sid}/messages", json={"content": "北京天气怎么样"})
    r = client.get(f"/api/sessions/{sid}/trace")
    assert r.status_code == 200
    assert r.json()["trace"][0]["tool"] == "weather"


# ---------- 异常与边界 ----------

def test_unknown_session_404():
    r = client.get("/api/sessions/nope/messages")
    assert r.status_code == 404
    r = client.get("/api/sessions/nope/trace")
    assert r.status_code == 404


def test_send_to_unknown_session_404():
    r = client.post("/api/sessions/no_such/messages", json={"content": "你好"})
    assert r.status_code == 404


def test_empty_content_422():
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post(f"/api/sessions/{sid}/messages", json={"content": ""})
    assert r.status_code == 422


def test_missing_content_422():
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post(f"/api/sessions/{sid}/messages", json={})
    assert r.status_code == 422


def test_busy_session_409():
    """会话 busy 时新消息返回 409（对应架构题模块四第 2 问）。"""
    sid = client.post("/api/sessions").json()["session_id"]
    s = manager.get(sid)
    s.state = "busy"
    r = client.post(f"/api/sessions/{sid}/messages", json={"content": "又来一条"})
    assert r.status_code == 409
    s.state = "idle"


def test_whitespace_content_allowed():
    """空白内容不崩溃（pydantic 校验通过，交由 MockLLM 处理）。"""
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post(f"/api/sessions/{sid}/messages", json={"content": "   "})
    assert r.status_code == 200


# ---------- 工具 ----------

def test_tools_list_contains_three_tools():
    r = client.get("/api/tools")
    assert r.status_code == 200
    tools = {t["name"] for t in r.json()["tools"]}
    assert {"calculator", "search", "weather"} <= tools


# ---------- api.json 契约 ----------

def test_api_json_is_valid_openapi_30():
    assert API_JSON.exists(), "api.json 未生成，请先运行 scripts/export_api.py"
    schema = json.loads(API_JSON.read_text(encoding="utf-8"))
    assert schema["openapi"].startswith("3.0.")
    assert "paths" in schema
    expected = {
        "/api/health", "/api/sessions",
        "/api/sessions/{session_id}/messages",
        "/api/tools", "/api/sessions/{session_id}/trace",
    }
    assert expected <= set(schema["paths"].keys())
