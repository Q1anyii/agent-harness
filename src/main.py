"""agent-harness 后端入口（最小闭环）：FastAPI + Agent 运行时。

- 会话管理：创建 / 列表 / 历史消息 / trace
- Agent 循环：MockLLM 决策 + 工具调用 + 轮次上限
- 存储为内存实现（落库留待后续迭代）
- 全局中间件（⑤）：请求计时 + 未捕获异常兜底 + 日志入库

启动：python src/main.py（默认 8000 端口，可用 PORT 环境变量覆盖）
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent.constants import (
    DEFAULT_PORT,
    DEFAULT_SESSION_DB,
    MAX_CONTEXT_TOKENS,
    MAX_ROUNDS,
)
from agent.llm import DeepSeekLLM, MockLLM
from agent.events import InMemoryQueue
from agent.log import LogRecord, LogStore, MemoryLogStore, SQLiteLogStore
from agent.memory import BM25Memory, MemoryExtractor
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


def _session_id_from_path(path: str) -> str:
    """从请求路径提取会话 ID（/api/sessions/{sid}/...），供日志按会话回溯。"""
    parts = path.split("/")
    if len(parts) >= 4 and parts[1] == "api" and parts[2] == "sessions":
        return parts[3]
    return ""


# 日志存储后端切换：memory（默认，测试/演示稳定） | sqlite（落库持久化）
# 与 SESSION_STORE 独立开关：日志关注点独立，可分别控制
log_store_type = os.environ.get("LOG_STORE", "memory")
if log_store_type == "sqlite":
    log_store: LogStore = SQLiteLogStore(os.environ.get("SESSION_DB", DEFAULT_SESSION_DB))
else:
    log_store = MemoryLogStore()


@app.middleware("http")
async def timing_and_error_middleware(request: Request, call_next):
    """全局中间件（⑤）：请求计时 + 未捕获异常兜底 + 日志入库。

    - 正常路径：call_next 返回响应 → 记录 status/duration_ms；
    - 异常路径：捕获未捕获异常 → 兜底生成 500 JSON 响应 + 记录 error；
    - HTTPException（404/409 等）由内层 ExceptionMiddleware 转响应，这里只负责计时记录。
    """
    start = time.perf_counter()
    status, error = 500, ""
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception as exc:  # 兜底：未捕获异常统一转 500 JSON，避免泄露堆栈
        error = f"{type(exc).__name__}: {exc}"
        response = JSONResponse(
            status_code=500,
            content={"detail": f"服务器内部错误: {type(exc).__name__}"},
        )
    finally:
        log_store.append(
            LogRecord(
                ts=datetime.now(timezone.utc).isoformat(),
                method=request.method,
                path=request.url.path,
                session_id=_session_id_from_path(request.url.path),
                status=status,
                duration_ms=round((time.perf_counter() - start) * 1000, 3),
                error=error,
            )
        )
    return response

# 流式事件队列（④）：生成侧（runtime）入队，前端轮询 /events 消费。
# 内存实现：会话隔离 + 单调 seq，断连后前端先全量刷新消息再续轮询。
event_queue = InMemoryQueue()

# 存储后端切换：memory（默认，测试/演示稳定，对象即引用）
#              | sqlite（落库持久化，真实运行：$env:SESSION_STORE="sqlite"）
store_type = os.environ.get("SESSION_STORE", "memory")
if store_type == "sqlite":
    manager = SQLiteSessionStore(os.environ.get("SESSION_DB", DEFAULT_SESSION_DB))
else:
    manager = SessionManager()

# LLM 后端切换：LLM_BACKEND=deepseek 走真实 DeepSeek，默认 mock 保证测试与演示稳定
backend = os.environ.get("LLM_BACKEND", "mock")
if backend == "deepseek":
    llm = DeepSeekLLM().init()
else:
    llm = MockLLM()

# 长期记忆（⑦）：BM25 检索 + 乘法衰减（内存实现，插件化策略可换 SQLite/向量）
memory = BM25Memory()
# 落库层 LLM 提取（⑦）：每轮 QA 经 LLM 提取自包含事实后落库（对齐 mem0 写入管线，
# 指代由"最近消息进提取上下文"消解）；Mock/DeepSeek 同一实例复用
memory_extractor = MemoryExtractor(llm)

runtime = AgentRuntime(
    llm=llm,
    max_rounds=MAX_ROUNDS,
    queue=event_queue,
    memory=memory,
    memory_extractor=memory_extractor,
    max_context_tokens=MAX_CONTEXT_TOKENS,
    # 注入会话仓储：互斥走存储层原子抢占（SQLite 模式跨请求可靠），
    # 历史在写回后立刻增量落库，下一轮 get() 不会读到缺回复的旧历史
    sessions=manager,
)


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
        event_queue.clear(session_id)  # 同步清理该会话的流式事件，防内存泄漏
        memory.forget(session_id)  # 同步清理该会话的长期记忆，防内存泄漏
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
        # 历史已在 runtime 写回后立刻增量落库（sqlite 模式），此处不再重复全量写
        result = await runtime.async_run(s, req.content)
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


@app.get("/api/sessions/{session_id}/events", tags=["chat"])
def get_events(session_id: str, since: int = 0) -> dict:
    """流式事件轮询端点（④）：返回 seq > since 的增量事件。

    前端 1s 级 setInterval 轮询；断连后先刷新 /messages 全量，再以
    since=最新 seq 续拉增量。since=0 返回队列内全部事件。
    """
    try:
        manager.get(session_id)  # 校验会话存在（404 语义一致）
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {
        "session_id": session_id,
        "events": event_queue.subscribe(session_id, since),
        "latest_seq": event_queue.latest_seq(session_id),
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", str(DEFAULT_PORT)))
    # 注意：Windows 上若端口处于 Hyper-V/WSL2 保留段（7449-8248）会报 WinError 10013，
    # 此时用 PORT 环境变量换端口，如：$env:PORT=18000
    uvicorn.run(app, host="0.0.0.0", port=port)
