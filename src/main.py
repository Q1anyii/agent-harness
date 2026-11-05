"""agent-harness 后端入口（最小闭环）：FastAPI + Agent 运行时。

- 会话管理：创建 / 列表 / 历史消息 / trace
- Agent 循环：MockLLM 决策 + 工具调用 + 轮次上限
- 存储为内存实现（落库留待后续迭代）

启动：python src/main.py（默认 8000 端口，可用 PORT 环境变量覆盖）
"""
from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, Field

from agent.llm import DeepSeekLLM, MockLLM
from agent.runtime import AgentRuntime
from agent.session import (
    SessionBusyError,
    SessionManager,
    SessionNotFoundError,
    SQLiteSessionStore,
)
from agent.tools import get_all_tools

app = FastAPI(
    title="agent-harness API",
    version="0.1.0",
    description="自实现 Agent harness 最小闭环：会话管理、Agent 循环、工具调用与 trace。",
)


def _custom_openapi() -> dict:
    """按 OpenAPI 3.0.3 生成契约（FastAPI 0.162 构造器不支持 openapi_version 参数）。"""
    if app.openapi_schema:
        return app.openapi_schema
    app.openapi_schema = get_openapi(
        title="agent-harness API",
        version="0.1.0",
        description="自实现 Agent harness 最小闭环：会话管理、Agent 循环、工具调用与 trace。",
        routes=app.routes,
        openapi_version="3.0.3",
    )
    return app.openapi_schema


app.openapi = _custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 存储后端切换：memory（默认，测试/演示稳定，对象即引用）
#              | sqlite（落库持久化，真实运行：$env:SESSION_STORE="sqlite"）
store_type = os.environ.get("SESSION_STORE", "memory")
if store_type == "sqlite":
    manager = SQLiteSessionStore(os.environ.get("SESSION_DB", "data/agent-harness.db"))
else:
    manager = SessionManager()

# LLM 后端切换：LLM_BACKEND=deepseek 走真实 DeepSeek，默认 mock 保证测试与演示稳定
backend = os.environ.get("LLM_BACKEND", "mock")
if backend == "deepseek":
    runtime = AgentRuntime(llm=DeepSeekLLM().init(), max_rounds=8)
else:
    runtime = AgentRuntime(llm=MockLLM(), max_rounds=8)


class ChatRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000, description="用户消息内容")


def _session_dict(s) -> dict:
    return {
        "session_id": s.session_id,
        "created_at": s.created_at,
        "state": s.state,
        "message_count": len(s.messages),
    }


@app.get("/api/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "service": "agent-harness"}


@app.post("/api/sessions", tags=["session"], status_code=201)
def create_session() -> dict:
    return _session_dict(manager.create())


@app.get("/api/sessions", tags=["session"])
def list_sessions() -> dict:
    sessions = manager.list()
    if not sessions:
        # 惰性默认会话：列表为空时自动新建，前端打开即有一个可用会话
        manager.create()
        sessions = manager.list()
    return {"sessions": [_session_dict(s) for s in sessions]}


@app.delete("/api/sessions/{session_id}", tags=["session"], status_code=204)
def delete_session(session_id: str) -> None:
    try:
        manager.remove(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在")


@app.get("/api/sessions/{session_id}/messages", tags=["session"])
def get_messages(session_id: str) -> dict:
    try:
        s = manager.get(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "messages": s.messages}


@app.post("/api/sessions/{session_id}/messages", tags=["chat"])
async def send_message(session_id: str, req: ChatRequest) -> dict:
    try:
        s = manager.get(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        result = await runtime.async_run(s, req.content)
        # 存储层持久化（memory 实现为 no-op；sqlite 模式落库消息/trace/状态）
        manager.save(s)
    except SessionBusyError:
        raise HTTPException(status_code=409, detail="会话正忙，请稍后重试")
    return {
        "session_id": session_id,
        "reply": result.reply,
        "trace": result.trace,
        "rounds_used": result.rounds_used,
        "max_rounds": result.max_rounds,
    }


@app.get("/api/tools", tags=["tools"])
def list_tools() -> dict:
    return {
        "tools": [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in get_all_tools()
        ]
    }


@app.get("/api/sessions/{session_id}/trace", tags=["trace"])
def get_trace(session_id: str) -> dict:
    try:
        s = manager.get(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "trace": s.traces}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    # 注意：Windows 上若端口处于 Hyper-V/WSL2 保留段（7449-8248）会报 WinError 10013，
    # 此时用 PORT 环境变量换端口，如：$env:PORT=18000
    uvicorn.run(app, host="0.0.0.0", port=port)
