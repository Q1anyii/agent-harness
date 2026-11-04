"""会话管理：内存存储，会话隔离（短期记忆的最小实现）。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Session:
    session_id: str
    created_at: str
    messages: list[dict] = field(default_factory=list)
    traces: list[dict] = field(default_factory=list)
    state: str = "idle"  # idle | busy


class SessionBusyError(Exception):
    """会话正忙，拒绝并发消息（对应架构题模块四第 2 问的最小实现）。"""


class SessionNotFoundError(Exception):
    pass


class SessionManager:
    """内存会话仓库：create / get / list / touch。"""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        session = Session(
            session_id=uuid.uuid4().hex,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(f"会话不存在: {session_id}")
        return session

    def list(self) -> list[Session]:
        return sorted(self._sessions.values(), key=lambda s: s.created_at, reverse=True)

    def append_trace(self, session: Session, trace: list[dict]) -> None:
        session.traces.extend(trace)
