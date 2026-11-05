"""请求日志存储：计时中间件/异常兜底 的落库抽象（⑤）。

- LogStore：日志存储接口（与 SessionStore 同风格的 Repository 抽象，
  未来换 PG/Redis 只换实现，调用方（中间件）不感知）。
- MemoryLogStore：内存实现（测试/演示默认，行为确定）。
- SQLiteLogStore：logs 表落库，与会话共用同一 db 文件，
  复用 session.connect_sqlite / session.sqlite_transaction（根因修复只写一次）。

记录一条 = 一次 HTTP 请求：method/path/session_id/status/耗时/错误（可选）。
"""
from __future__ import annotations

import os
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass

from agent.session import connect_sqlite, sqlite_transaction


@dataclass
class LogRecord:
    """一条请求日志：耗时与错误由中间件在请求生命周期结束时写入。"""

    ts: str  # ISO 时间（UTC）
    method: str
    path: str
    status: int
    duration_ms: float
    session_id: str = ""  # 从 path 中提取（/api/sessions/{sid}/...），便于按会话回溯
    error: str = ""  # 未捕获异常时填充，正常请求为空


class LogStore(ABC):
    """日志存储抽象：实现可换（内存 / SQLite / 未来 PG）。"""

    @abstractmethod
    def append(self, record: LogRecord) -> None: ...

    @abstractmethod
    def list(self, limit: int = 200) -> list[LogRecord]: ...


class MemoryLogStore(LogStore):
    """内存日志仓库：append 追加，list 返回最新在前（调用方读最近记录方便）。"""

    def __init__(self) -> None:
        self._records: list[LogRecord] = []

    def append(self, record: LogRecord) -> None:
        self._records.append(record)

    def list(self, limit: int = 200) -> list[LogRecord]:
        return list(reversed(self._records[-limit:]))


class SQLiteLogStore(LogStore):
    """SQLite 落库实现：logs 表（与会话存储共用 connect_sqlite/sqlite_transaction）。

    只使用标准 SQL（参数化 + INSERT/SELECT），未来换 PG 仅换驱动。
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        with sqlite_transaction(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    session_id TEXT,
                    status INTEGER NOT NULL,
                    duration_ms REAL NOT NULL,
                    error TEXT
                )
                """
            )

    def append(self, record: LogRecord) -> None:
        with sqlite_transaction(self.db_path) as conn:
            conn.execute(
                "INSERT INTO logs (ts, method, path, session_id, status, duration_ms, error)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.ts,
                    record.method,
                    record.path,
                    record.session_id or None,
                    record.status,
                    record.duration_ms,
                    record.error or None,
                ),
            )

    def list(self, limit: int = 200) -> list[LogRecord]:
        with sqlite_transaction(self.db_path) as conn:
            rows = conn.execute(
                "SELECT ts, method, path, session_id, status, duration_ms, error"
                " FROM logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            LogRecord(
                ts=r[0],
                method=r[1],
                path=r[2],
                session_id=r[3] or "",
                status=r[4],
                duration_ms=r[5],
                error=r[6] or "",
            )
            for r in rows
        ]
