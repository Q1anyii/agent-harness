"""长期记忆测试（⑦）：BM25 检索相关性 + 乘法衰减 + runtime 接入闭环。"""
from __future__ import annotations

from agent.memory import BM25Memory, MemoryEntry
from agent.runtime import AgentRuntime
from agent.session import Session
from agent.tools import get_tool


def test_tokenize_cjk_and_english():
    """中文单字 + 英文按词小写切分（无分词器折中）。"""
    tokens = BM25Memory._tokenize("南昌天气 Sunny")
    assert "南" in tokens and "昌" in tokens and "天" in tokens and "气" in tokens
    assert "sunny" in tokens


def test_remember_and_recall_related():
    mem = BM25Memory()
    mem.remember("s1", "Q: 南昌天气\nA: 南昌多云 20 度")
    mem.remember("s1", "Q: 帮我算 1+10\nA: 等于 11")
    hits = mem.recall("南昌天气怎么样", k=5, session_id="s1")
    assert len(hits) == 1  # 无关记忆无共享词 → BM25 分数 0 被过滤
    # 含"南昌/天气"关键词的记忆被召回
    assert "南昌" in hits[0].content


def test_recall_unrelated_returns_empty():
    mem = BM25Memory()
    mem.remember("s1", "南昌天气 20 度")
    # 与 query 无共享词的记忆不召回（分数 0 过滤），避免无关记忆塞进上下文
    assert mem.recall("如何写 Dockerfile", k=5, session_id="s1") == []


def test_multiplicative_decay_on_repeat_recall():
    """乘法衰减：同相关度记忆，被召回过的（衰减 0.9^1）让位给未衰减的（0.9^0）。"""
    mem = BM25Memory(decay_factor=0.9)
    mem.remember("s1", "南昌天气 20 度")
    mem.remember("s1", "南昌天气 25 度")
    # 两条 BM25 分相同（同词频同长度），k=1 时首次命中列表第一条
    first = mem.recall("南昌天气", k=1, session_id="s1")
    assert "20" in first[0].content
    # 第二次召回：命中过的衰减到 0.9，未命中的保持 1.0 → 换一条
    second = mem.recall("南昌天气", k=1, session_id="s1")
    assert "25" in second[0].content


def test_session_isolation():
    """记忆按会话隔离：A 会话的记忆不会召回进 B 会话。"""
    mem = BM25Memory()
    mem.remember("s1", "南昌天气 20 度")
    mem.remember("s2", "北京天气 17 度")
    hits = mem.recall("天气", k=5, session_id="s1")
    assert len(hits) == 1
    assert "南昌" in hits[0].content


def test_forget_clears_session():
    mem = BM25Memory()
    mem.remember("s1", "南昌天气 20 度")
    mem.remember("s2", "北京天气 17 度")
    mem.forget("s1")
    assert mem.recall("天气", k=5, session_id="s1") == []
    assert len(mem.recall("天气", k=5, session_id="s2")) == 1


def test_runtime_qa_persisted_to_memory():
    """runtime 接入闭环：一轮 QA 后记忆落库一条，下一轮可被召回进 system。"""
    mem = BM25Memory()
    rt = AgentRuntime(llm=_FakeLLM(), memory=mem)
    s = Session(session_id="s1", created_at="t")
    rt.run(s, "南昌天气如何")
    # QA 已落库
    assert len(mem.recall("天气", k=5, session_id="s1")) == 1
    # 下一轮 build_messages 时，相关记忆被召回并拼入本次 system（动态段）
    s2 = Session(session_id="s1", created_at="t")
    msgs = rt._build_messages(s2, "南昌天气如何")
    assert "【长期记忆" in msgs[0]["content"]
    assert "南昌" in msgs[0]["content"]


def test_runtime_without_memory_no_recall():
    """未配置记忆：system 不含记忆段（默认行为，兼容既有测试）。"""
    rt = AgentRuntime(llm=_FakeLLM())
    s = Session(session_id="s1", created_at="t")
    msgs = rt._build_messages(s, "南昌天气如何")
    assert "【长期记忆" not in msgs[0]["content"]


class _FakeLLM:
    """固定直接回复的假 LLM（不发工具调用），专注记忆链路。"""

    def generate(self, messages):
        from agent.llm import LLMResponse
        return LLMResponse(content="南昌多云，20 度。", reasoning="查天气", tool_calls=None)

    async def async_generate(self, messages):
        return self.generate(messages)
