"""流式事件队列：解耦"生成侧"与"传输侧"。

- EventQueue：抽象接口（实现可换：内存 / 未来 Redis 队列）
- InMemoryQueue：内存实现（按会话隔离的 deque + 单调 seq + 锁）

设计动机（对应需求"流式输出"）：
- 生成侧（AgentRuntime）把关键节点作为事件 publish：reasoning / tool_call / tool_result / message_delta
- 传输侧（前端）轮询 GET /events?since=N 拿增量，断连后先全量刷新消息再续轮询
- 队列只承载"生成过程的实时事件"；最终消息以服务端 session.messages 为准（真相源）

事件协议（type 字段）：
- reasoning     {"type":"reasoning","content":str}            思考过程（LLM reasoning_content）
- tool_call     {"type":"tool_call","id":str,"name":str,"args":dict}   决定调用工具
- tool_result   {"type":"tool_result","id":str,"name":str,"result":str,"status":str,"duration_ms":float}
- message_delta {"type":"message_delta","delta":str,"done":bool}       最终回复增量块（done 标记收尾）

每条事件带单调递增 seq，前端用 since 参数增量拉取。
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections import defaultdict, deque


class EventQueue(ABC):
    """流式事件队列抽象：实现可换（内存 / 未来 Redis Stream 等）。"""

    @abstractmethod
    def publish(self, session_id: str, event: dict) -> dict:
        """生成侧推送一条事件（自动附加 seq）。返回带 seq 的完整事件。"""

    @abstractmethod
    def subscribe(self, session_id: str, since: int) -> list[dict]:
        """消费侧拉取 seq > since 的增量事件（断连续拉/首次拉全量用 since=0）。"""

    @abstractmethod
    def latest_seq(self, session_id: str) -> int:
        """当前最大 seq（前端轮询的续拉锚点）。"""

    @abstractmethod
    def clear(self, session_id: str) -> None:
        """会话删除时清理其事件（防泄漏）。"""


class InMemoryQueue(EventQueue):
    """内存实现：每会话一个 deque（保留最近 max_per_session 条）+ 单调 seq。

    - 线程安全：publish 可能来自 async 上下文，subscribe 来自 FastAPI 线程池，
      统一用锁保护（deque 的 append/popleft 单操作虽原子，seq 递增需复合保护）。
    - 保留窗口：轮询间隔（秒级）内事件远小于 max_per_session，不会漏事件；
      窗口外的旧事件由"断连先全量刷新"兜底。
    """

    def __init__(self, max_per_session: int = 500) -> None:
        self._events: dict[str, deque] = defaultdict(deque)
        self._seqs: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self._max = max_per_session

    def publish(self, session_id: str, event: dict) -> dict:
        with self._lock:
            self._seqs[session_id] += 1
            full = {"seq": self._seqs[session_id], **event}
            dq = self._events[session_id]
            dq.append(full)
            # 只保留最近 N 条，防会话长期运行内存膨胀
            while len(dq) > self._max:
                dq.popleft()
            return full

    def subscribe(self, session_id: str, since: int) -> list[dict]:
        with self._lock:
            dq = self._events.get(session_id)
            if not dq:
                return []
            # deque 内 seq 单调递增，线性过滤即可（事件量小）
            return [e for e in dq if e["seq"] > since]

    def latest_seq(self, session_id: str) -> int:
        with self._lock:
            return self._seqs.get(session_id, 0)

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._events.pop(session_id, None)
            self._seqs.pop(session_id, None)
