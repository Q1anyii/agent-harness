"""长期记忆（⑦）：MemoryStrategy 插件化抽象 + BM25 检索 + 乘法衰减 + LLM 提取落库。

架构对齐 Mitta 的 mem0 写入/检索管线（见 src/service/memory_service.py
与 mem0 ADDITIVE_EXTRACTION_PROMPT，MEM0_DEEP_DIVE.md §1）：
- 插件化策略：MemoryStrategy 是抽象接口，检索算法可换（BM25 / 未来向量 / 混合）；
- BM25 检索：标准 Okapi BM25（k1=1.5, b=0.75），中文按单字切分、英文按词切分
  （无分词器时的保守折中，本地规模足够）；
- 乘法衰减：每条记忆带 access_count（被召回次数），检索排序分 =
  BM25 相关性 × decay_factor^access_count。被反复召回的旧记忆分数打折，
  鼓励模型关注新/未被充分使用的记忆，防止"记忆固化"（Mitta _reweight mult 模式思路）；
- 落库层 LLM 提取（本文件的 MemoryExtractor，对齐 mem0 P2/P0）：
  每轮 QA 不直接存原始文本，而是把「已有记忆 + 最近 k 条消息 + 本轮问答」交给 LLM，
  提取出【自包含】事实后再落库——指代（如"那南昌呢"承接上文"北京天气"）在提取阶段
  就被最近上下文消解，记忆不会存成残缺的孤立片段；
- md5 去重（对齐 mem0 P4/P5）：完全重复的事实不重复入库。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

from agent.llm import LLMClient


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
    """BM25 检索 + 乘法衰减的内存实现（本地规模；存储可后续换 SQLite）。"""

    # Okapi BM25 标准参数：k1 控制词频饱和，b 控制文档长度归一化强度
    K1 = 1.5
    B = 0.75

    def __init__(self, decay_factor: float = 0.9) -> None:
        self._entries: list[MemoryEntry] = []
        self.decay_factor = decay_factor  # 每次命中衰减倍率（0~1）

    # ---- 策略接口 ----

    def remember(self, session_id: str, content: str) -> None:
        # md5 去重（对齐 mem0 P4/P5）：与该会话已有记忆完全重复的事实不重复入库
        if any(
            self._hash(e.content) == self._hash(content)
            for e in self._entries
            if e.session_id == session_id
        ):
            return
        self._entries.append(
            MemoryEntry(
                id=uuid.uuid4().hex[:12],
                session_id=session_id,
                content=content,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

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


# 提取器 system prompt 首行标记：MockLLM 靠它识别"这是记忆提取任务"，
# 走规则提取分支（真实 LLM 则按提示词直接产出 JSON）。
EXTRACTOR_SYSTEM_PROMPT = (
    "你是长期记忆提取器。从对话中提取值得长期记住的事实。\n"
    "规则：\n"
    "- 每条事实必须【自包含】：独立成句、含必要上下文，可直接作为检索记忆使用；\n"
    "  若新消息有指代（如“那南昌呢”承接上文“北京天气”），必须结合最近消息补全上下文，"
    "不要存孤立片段；\n"
    "- 用与用户消息相同的语言记录（中文就用中文，保留地名/数值/术语）；\n"
    "- 只提取稳定、可复用的信息；纯临时问答（如一次性计算）可跳过；\n"
    "- 与已有记忆完全重复的事实不要输出；\n"
    "只输出 JSON：{\"facts\": [\"事实1\", \"事实2\"]}，不要输出任何其他文字。"
)


def build_extract_prompt(
    existing: list["MemoryEntry"],
    new_qa: str,
    recent_messages: list[str],
) -> str:
    """构造提取 prompt（对齐 mem0 generate_additive_extraction_prompt 的段落结构）。

    关键：把「已有记忆 + 最近消息」都放进提取上下文——LLM 提取时能据此
    消解指代、产出自包含事实（Mem0 P0 最近 10 条 + P1 已有记忆 + P2 提取）。
    """
    existing_block = json.dumps(
        [{"id": e.id, "content": e.content} for e in existing],
        ensure_ascii=False,
        indent=1,
    )
    recent_block = "\n".join(recent_messages) if recent_messages else "（无）"
    return (
        "## Existing Memories\n" + existing_block
        + "\n\n## Last k Messages\n" + recent_block
        + "\n\n## New Messages\n" + new_qa
    )


class MemoryExtractor:
    """落库层 LLM 提取（对齐 mem0 P2 ADD-only 提取 + Mitta memory_node 提交路径）。

    runtime 每轮 QA 结束后调用：extract(已有相关记忆, 本轮问答, 最近消息) → 事实列表，
    由 runtime 逐条 remember 落库。LLM 失败/输出非法时降级为「原始 QA 单条」，
    保证记忆写入永远可用（对齐 Mitta「记忆是优化而非硬依赖」哲学）。
    """

    def __init__(self, llm: LLMClient, recent_k: int = 10) -> None:
        self.llm = llm
        self.recent_k = recent_k  # 提取上下文携带的最近消息条数（Mem0 P0 的 limit=10）

    def extract(
        self,
        existing: list[MemoryEntry],
        new_qa: str,
        recent_messages: list[str],
    ) -> list[str]:
        """同步提取：返回要落库的自包含事实列表（md5 去重由 remember 负责）。"""
        prompt = build_extract_prompt(existing, new_qa, recent_messages[-self.recent_k:])
        resp = self.llm.generate([
            {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        return self._parse(resp.content, new_qa)

    @staticmethod
    def _parse(raw: str | None, fallback_qa: str) -> list[str]:
        """解析 LLM 的 {"facts": [...]} JSON；失败/空结果降级为原始 QA 单条。

        容错：去掉 ```json 代码块围栏与首尾空白后再解析（模型常见输出偏差）。
        """
        if not raw:
            return [fallback_qa]
        text = raw.strip()
        if text.startswith("```"):
            # 剥掉 ```json ... ``` 围栏
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            data = json.loads(text)
            facts = [str(f) for f in data.get("facts", []) if str(f).strip()]
        except (json.JSONDecodeError, AttributeError):
            facts = []
        # 提取失败/无事实 → 降级存原始 QA（保证写入不丢）
        return facts or [fallback_qa]
