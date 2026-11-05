"""长期记忆（⑦）：MemoryStrategy 插件化抽象 + BM25 检索 + 乘法衰减。

架构对齐 Mitta 的记忆策略（用户方案原话，见 docs/context与记忆机制设计.md）：
- 插件化策略：MemoryStrategy 是抽象接口，检索算法可换（BM25 / 未来向量 / 混合）；
- BM25 检索：标准 Okapi BM25（k1=1.5, b=0.75），中文按单字切分、英文按词切分
  （无分词器时的保守折中，笔试规模足够）；
- 乘法衰减：每条记忆带 access_count（被召回次数），检索排序分 =
  BM25 相关性 × decay_factor^access_count。被反复召回的旧记忆分数打折，
  鼓励模型关注新/未被充分使用的记忆，防止"记忆固化"（Mem0/Mitta 乘性衰减思路）。
- 每轮 QA 落库 + 每轮召回 top-k 拼入上下文（runtime 接入）；
  短期窗口裁掉的信息仍可经长期记忆召回，形成闭环。
"""
from __future__ import annotations

import math
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class MemoryEntry:
    """一条长期记忆：QA 合并存 content，access_count 供乘法衰减。"""

    id: str
    session_id: str
    content: str
    created_at: str
    access_count: int = 0  # 被 recall 命中的累计次数（衰减依据）


class MemoryStrategy(ABC):
    """长期记忆插件化策略：实现可换（BM25 / 向量 / 混合）。

    remember 写、recall 读（返回按衰减后分数排序的记忆）、forget 清会话。
    """

    @abstractmethod
    def remember(self, session_id: str, content: str) -> None: ...

    @abstractmethod
    def recall(
        self, query: str, k: int = 10, session_id: str | None = None
    ) -> list[MemoryEntry]: ...

    @abstractmethod
    def forget(self, session_id: str) -> None: ...


class BM25Memory(MemoryStrategy):
    """BM25 检索 + 乘法衰减的内存实现（笔试规模；存储可后续换 SQLite）。"""

    # Okapi BM25 标准参数：k1 控制词频饱和，b 控制文档长度归一化强度
    K1 = 1.5
    B = 0.75

    def __init__(self, decay_factor: float = 0.9) -> None:
        self._entries: list[MemoryEntry] = []
        self.decay_factor = decay_factor  # 每次命中衰减倍率（0~1）

    # ---- 策略接口 ----

    def remember(self, session_id: str, content: str) -> None:
        self._entries.append(
            MemoryEntry(
                id=uuid.uuid4().hex[:12],
                session_id=session_id,
                content=content,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )

    def recall(
        self, query: str, k: int = 10, session_id: str | None = None
    ) -> list[MemoryEntry]:
        """检索与 query 最相关的 k 条记忆（按 衰减后分数 降序）。

        - 只召回分数 > 0 的条目（与 query 有共享词才有相关性）；
        - 命中条目 access_count + 1：下次检索时乘法衰减生效。
        """
        entries = [
            e for e in self._entries
            if session_id is None or e.session_id == session_id
        ]
        if not entries:
            return []
        docs = [self._tokenize(e.content) for e in entries]
        avgdl = sum(len(d) for d in docs) / len(docs)
        # 文档频率 df：每个词出现在几条记忆里（BM25 IDF 需要）
        df: dict[str, int] = {}
        for d in docs:
            for term in set(d):
                df[term] = df.get(term, 0) + 1
        query_terms = self._tokenize(query)

        scored: list[tuple[float, MemoryEntry]] = []
        for entry, doc in zip(entries, docs):
            raw = self._bm25_score(query_terms, doc, len(doc), avgdl, df, len(docs))
            if raw <= 0:
                continue  # 无相关性（无共享词）不召回，避免把无关记忆塞进上下文
            # 乘法衰减：被召回越多，分数越低（decay_factor^access_count）
            decayed = raw * (self.decay_factor ** entry.access_count)
            scored.append((decayed, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [e for _, e in scored[:k]]
        for e in top:
            e.access_count += 1
        return top

    def forget(self, session_id: str) -> None:
        self._entries = [e for e in self._entries if e.session_id != session_id]

    # ---- BM25 实现 ----

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """无分词器时的保守切分：CJK 单字 + 英文/数字按词（小写）。"""
        tokens: list[str] = []
        for ch in text:
            if "\u4e00" <= ch <= "\u9fff":
                tokens.append(ch)
        tokens += re.findall(r"[a-z0-9]+", text.lower())
        return tokens

    @staticmethod
    def _bm25_score(
        query_terms: list[str],
        doc_terms: list[str],
        doc_len: int,
        avgdl: float,
        df: dict[str, int],
        n_docs: int,
    ) -> float:
        """Okapi BM25：IDF × 词频饱和度（k1/b 归一化），逐查询词累加。"""
        score = 0.0
        for term in set(query_terms):
            tf = doc_terms.count(term)
            if tf == 0:
                continue
            idf = math.log((n_docs - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5) + 1)
            denom = tf + BM25Memory.K1 * (1 - BM25Memory.B + BM25Memory.B * doc_len / avgdl)
            score += idf * (tf * (BM25Memory.K1 + 1)) / denom
        return score
