"""会话管理：存储抽象 + 内存/SQLite 双实现。

- SessionStore：存储层接口（Repository 模式），读写会话/消息/trace。
  测试与演示用 SessionManager（内存），真实运行可切 SQLiteSessionStore（落库持久化）。
- Session：会话对象 = 短期记忆的最小实现（消息历史 + trace + 状态机 state）。
- system_prompt：会话开始时构造一次（角色+能力+工具约定），运行时插入消息首条，
  不写入 session.messages（对话历史保持干净，仅存文本字段）。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Session:
    session_id: str
    created_at: str
    messages: list[dict] = field(default_factory=list)
    traces: list[dict] = field(default_factory=list)
    state: str = "idle"  # idle | busy
    system_prompt: str = ""  # 会话级 system prompt（首次运行时构造，之后复用）


class SessionBusyError(Exception):
    """会话正忙，拒绝并发消息（对应架构题模块四第 2 问的最小实现）。"""


class SessionNotFoundError(Exception):
    pass


class SessionStore(ABC):
    """存储层抽象：实现可换（内存 / SQLite / 未来 PG）。

    写路径：调用方修改 Session 对象后显式 save() 落库；
    读路径：get() 从存储重建最新 Session（含消息与 trace）。
    """

    @abstractmethod
    def create(self) -> Session: ...

    @abstractmethod
    def get(self, session_id: str) -> Session: ...

    @abstractmethod
    def list(self) -> list[Session]: ...

    @abstractmethod
    def remove(self, session_id: str) -> None: ...

    @abstractmethod
    def save(self, session: Session) -> None: ...

    @abstractmethod
    def try_acquire(self, session_id: str) -> bool:
        """原子抢占会话（idle → busy）：True 抢到，False 本轮已被占用。

        互斥必须落在存储层：`Session.state` 是对象内存字段，
        SQLite 实现每次 get() 都重建对象，靠内存字段判断在并发下必然失效。
        """
        ...

    @abstractmethod
    def release(self, session_id: str) -> None:
        """释放会话（busy → idle）；重复调用与已删除会话均静默幂等。"""
        ...


class SessionManager(SessionStore):
    """内存会话仓库：create / get / list / remove / save。

    内存实现中 Session 对象本身就是引用，save() 无需额外动作（保持接口一致）。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        # 保护 state 的 idle↔busy 转移：async 单事件循环内本就是原子的，
        # 但同步入口（asyncio.run / 测试 / 多线程调用）也走这里，加锁后语义统一
        self._state_lock = threading.Lock()

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

    def remove(self, session_id: str) -> None:
        """删除会话；不存在时抛 SessionNotFoundError。"""
        if session_id not in self._sessions:
            raise SessionNotFoundError(f"会话不存在: {session_id}")
        del self._sessions[session_id]

    def save(self, session: Session) -> None:
        """内存实现：对象即引用，无需额外持久化。"""

    def try_acquire(self, session_id: str) -> bool:
        """原子抢占：锁内判断 state 再置 busy（内存实现的 CAS 等价物）。"""
        with self._state_lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(f"会话不存在: {session_id}")
            if session.state != "idle":
                return False
            session.state = "busy"
            return True

    def release(self, session_id: str) -> None:
        """释放会话；会话已被删除时静默返回（幂等兜底）。"""
        with self._state_lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.state = "idle"

    def append_trace(self, session: Session, traces: list[dict]) -> None:
        """向会话追加工具调用 trace（内存实现：直接扩展对象引用）。"""
        session.traces.extend(traces)


def connect_sqlite(db_path: str) -> sqlite3.Connection:
    """打开 SQLite 连接（会话/日志落库共用，根因修复只写一次）。

    - 每次操作新连接：避免跨线程共享连接（FastAPI 线程池 + 事件循环并发访问）
    - 事务日志放内存（journal_mode=MEMORY）：当前运行环境（沙箱）会拦截 SQLite
      默认 rollback journal 文件（.db-journal）的落盘，导致 DDL/DML 静默失效；
      MEMORY 模式绕过该拦截，数据库主文件本身仍正常持久化（实测验证）。
      崩溃安全性略降（最后未同步事务可能丢失），对单机本地部署可接受。
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=MEMORY")
    return conn


@contextmanager
def sqlite_transaction(db_path: str):
    """短连接事务上下文：成功 commit / 异常 rollback / 最后必 close。

    注意：`with sqlite3.connect(...) as conn` 只提交不关闭连接，
    Windows 下会因文件句柄未释放导致后续无法删除数据库文件（实测 PermissionError）。
    """
    conn = connect_sqlite(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class SQLiteSessionStore(SessionStore):
    """SQLite 落库实现：sessions / messages / traces 三表（logs 由中间件另用）。

    - 每次操作独立短连接（check_same_thread 安全，适配 FastAPI 线程池/事件循环）
    - 只使用标准 SQL（参数化 + INSERT/UPDATE），未来换 PG 仅换驱动
    - save() 全量同步该会话的 messages/traces（本地规模，简单可靠）
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        # 复用模块级 connect_sqlite：每次操作新连接（跨线程安全）+ journal_mode=MEMORY（沙箱根因）
        return connect_sqlite(self.db_path)

    @contextmanager
    def _session(self):
        # 复用模块级 sqlite_transaction：短连接 commit/rollback/close（Windows 文件句柄根因）
        with sqlite_transaction(self.db_path) as conn:
            yield conn

    def _init_schema(self) -> None:
        with self._session() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'idle'
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    extra TEXT
                );
                CREATE TABLE IF NOT EXISTS traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    args TEXT,
                    result TEXT,
                    status TEXT,
                    duration_ms REAL
                );
                """
            )

    def create(self) -> Session:
        session = Session(
            session_id=uuid.uuid4().hex,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._session() as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, created_at, state) VALUES (?, ?, ?)",
                (session.session_id, session.created_at, session.state),
            )
        return session

    def get(self, session_id: str) -> Session:
        with self._session() as conn:
            row = conn.execute(
                "SELECT session_id, created_at, state FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise SessionNotFoundError(f"会话不存在: {session_id}")
            msg_rows = conn.execute(
                "SELECT role, content, extra FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
            trace_rows = conn.execute(
                "SELECT tool, args, result, status, duration_ms FROM traces WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        messages = [
            {
                "role": r[0],
                "content": r[1],
                **(json.loads(r[2]) if r[2] else {}),
            }
            for r in msg_rows
        ]
        traces = [
            {
                "tool": t[0],
                "args": json.loads(t[1]) if t[1] else {},
                "result": t[2],
                "status": t[3],
                "duration_ms": t[4],
            }
            for t in trace_rows
        ]
        return Session(
            session_id=row[0],
            created_at=row[1],
            messages=messages,
            traces=traces,
            state=row[2],
        )

    def list(self) -> list[Session]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT session_id, created_at, state FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        # 本地规模：逐会话加载消息，保证 message_count 与接口语义一致
        return [self.get(r[0]) for r in rows]

    def remove(self, session_id: str) -> None:
        with self._session() as conn:
            if conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone() is None:
                raise SessionNotFoundError(f"会话不存在: {session_id}")
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM traces WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def save(self, session: Session) -> None:
        """增量同步：upsert sessions 行 + 只追加尚未落库的 messages/traces。

        用"库内行数 vs 内存条数"的差值算出新增部分（messages/traces 只追加不裁剪：
        trim 只作用于发给 LLM 的副本、不回写 session），成本从 O(会话总长) 降到
        O(本次新增)。上一轮若落库失败，下一轮按行数差会把它一并补上。
        """
        with self._session() as conn:
            cur = conn.execute(
                "UPDATE sessions SET state = ? WHERE session_id = ?",
                (session.state, session.session_id),
            )
            if cur.rowcount == 0:
                conn.execute(
                    "INSERT INTO sessions (session_id, created_at, state) VALUES (?, ?, ?)",
                    (session.session_id, session.created_at, session.state),
                )
            stored_messages = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session.session_id,)
            ).fetchone()[0]
            pending = session.messages[stored_messages:]
            if pending:
                conn.executemany(
                    "INSERT INTO messages (session_id, role, content, extra) VALUES (?, ?, ?, ?)",
                    [
                        (
                            session.session_id,
                            m.get("role", ""),
                            m.get("content"),
                            json.dumps(
                                {k: v for k, v in m.items() if k not in ("role", "content")},
                                ensure_ascii=False,
                            )
                            if any(k not in ("role", "content") for k in m)
                            else None,
                        )
                        for m in pending
                    ],
                )
            stored_traces = conn.execute(
                "SELECT COUNT(*) FROM traces WHERE session_id = ?", (session.session_id,)
            ).fetchone()[0]
            new_traces = session.traces[stored_traces:]
            if new_traces:
                conn.executemany(
                    "INSERT INTO traces (session_id, tool, args, result, status, duration_ms) VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            session.session_id,
                            t.get("tool", ""),
                            json.dumps(t.get("args", {}), ensure_ascii=False),
                            t.get("result", ""),
                            t.get("status", ""),
                            t.get("duration_ms"),
                        )
                        for t in new_traces
                    ],
                )

    def try_acquire(self, session_id: str) -> bool:
        """原子抢占：CAS 把 idle 改成 busy，并发下只有一个 UPDATE 能命中。

        这是跨请求互斥的可靠实现——`Session.state` 是内存副本字段，SQLite 模式
        每次 get() 都重建对象，靠对象字段判断会让两个请求双双放行。
        """
        with self._session() as conn:
            cur = conn.execute(
                "UPDATE sessions SET state = 'busy' WHERE session_id = ? AND state = 'idle'",
                (session_id,),
            )
            if cur.rowcount == 1:
                return True
            # 区分"忙"与"不存在"：不存在抛 NotFound（404），忙返回 False（409）
            row = conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise SessionNotFoundError(f"会话不存在: {session_id}")
            return False

    def release(self, session_id: str) -> None:
        """释放：busy → idle；会话不存在时静默（幂等兜底）。"""
        with self._session() as conn:
            conn.execute(
                "UPDATE sessions SET state = 'idle' WHERE session_id = ?", (session_id,)
            )
