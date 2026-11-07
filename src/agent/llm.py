"""LLM 抽象与实现。

最小闭环阶段使用 MockLLM（规则式）：无需 API Key 即可跑通前后端联调。
真实大模型接入 DeepSeekLLM（OpenAI-compatible chat/completions）：
- init() 延迟导入 openai，读环境变量创建客户端
- generate() 把内部消息历史转换为 OpenAI 格式，下发工具 schema，解析响应
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from agent.constants import LLM_TIMEOUT_SECONDS
from agent.router import extract_args, route
from agent.tools import get_all_tools
from dotenv import load_dotenv


# 加载 .env 兜底配置。注意不 override：shell 显式设置的环境变量优先于 .env，
# 否则测试命令里的 $env:LLM_BACKEND="mock" 会被 .env 的 deepseek 覆盖，测试误走真实 LLM。
load_dotenv()


@dataclass(frozen=True)
class ToolCall:
    """一次工具调用的决策。

    id 是 OpenAI tool_call 的调用 id（"订单号"），tool 消息回显时使用；
    Mock 路径可留空，由 runtime 用 uuid 兜底生成。
    """

    name: str
    args: dict[str, str] = field(default_factory=dict)
    id: str = ""


@dataclass(frozen=True)
class LLMResponse:
    """LLM 一次决策的结果：要么给文本回复（tool_calls=None），要么给工具调用列表（content=None）。

    reasoning：思考过程文本（如 DeepSeek 的 reasoning_content），可为空；
    前端把它渲染为 AI 消息块内的"思考过程"（⑥ reasoning，与②工具块一体）。
    """

    content: str | None
    tool_calls: list[ToolCall] | None
    reasoning: str | None = None


class LLMClient(ABC):
    """Agent 与大模型的唯一交互点。"""

    @abstractmethod
    def init(self) -> None:
        """初始化底层客户端（如 OpenAI-compatible client）。Mock 可空实现。"""

    @abstractmethod
    def generate(self, messages: list[dict]) -> LLMResponse:
        """输入消息历史，返回文本回复或工具调用列表。"""

    @abstractmethod
    async def async_generate(self, messages: list[dict]) -> LLMResponse:
        """输入消息历史，异步返回文本回复或工具调用列表。"""


class DeepSeekLLM(LLMClient):
    """真实 DeepSeek（OpenAI 兼容协议）接入：消息转换 + 工具调用解析。"""

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.client = None  # 延迟到 init() 创建，测试可注入 fake client
        self.async_client = None

    def init(self) -> DeepSeekLLM:
        """读环境变量/缺省值 → 创建 OpenAI 兼容客户端。"""
        from openai import OpenAI, AsyncOpenAI

        # 1) 环境变量兜底：未显式传入时读 .env（模块顶部 load_dotenv 已加载）
        self.api_key = self.api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.base_url = self.base_url or os.environ.get(
            "BASE_URL", "https://api.deepseek.com"
        )
        self.model = self.model or os.environ.get("MODEL_NAME", "deepseek-flash")

        # 2) 快速失败：key 缺失立刻报错，而不是让 OpenAI 库深层报错
        if not self.api_key:
            raise ValueError("缺少 DEEPSEEK_API_KEY：请在 .env 配置或传入 api_key")

        # 3) 真正创建客户端（openai 延迟导入，避免未安装依赖时模块导入即失败）
        self.async_client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=LLM_TIMEOUT_SECONDS)
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=LLM_TIMEOUT_SECONDS)
        return self  # 支持链式调用：DeepSeekLLM().init()

    def generate(self, messages: list[dict]) -> LLMResponse:
        """把内部消息历史转换为 OpenAI 兼容格式，下发工具 schema，解析模型响应。"""
        # 1) 内部消息 → OpenAI 格式（构造新列表 out，不原地改原消息）
        api_messages = self._to_openai_messages(messages)
        # 2) 工具注册表 → OpenAI tools 参数（function schema 列表）
        tools = [self._to_tool_schema(t) for t in get_all_tools()]
        # 3) 调用 DeepSeek（OpenAI 兼容 chat/completions）
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            tools=tools,
        )
        # 4) 解析响应：有 tool_calls → 解析成 ToolCall 列表；否则 → 纯文本。
        #    reasoning_content（DeepSeek 思考过程）非空时一并带出。
        message = resp.choices[0].message
        reasoning = getattr(message, "reasoning_content", None) or None
        if getattr(message, "tool_calls", None):
            calls = []
            for tc in message.tool_calls:
                fn = tc.function
                # arguments 是 JSON 字符串，必须 json.loads 还原成参数字典；
                # 解析失败兜底为空参数字典（工具层会给出"参数不匹配"错误）
                try:
                    args = json.loads(fn.arguments) if fn.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                calls.append(ToolCall(name=fn.name, args=args, id=tc.id))
            return LLMResponse(content=None, tool_calls=calls, reasoning=reasoning)
        return LLMResponse(content=message.content, tool_calls=None, reasoning=reasoning)

    async def async_generate(self, messages: list[dict]) -> LLMResponse:
        api_messages = self._to_openai_messages(messages)
        # 2) 工具注册表 → OpenAI tools 参数（function schema 列表）
        tools = [self._to_tool_schema(t) for t in get_all_tools()]
        # 3) 调用 DeepSeek（OpenAI 兼容 chat/completions）
        resp = await self.async_client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            tools=tools,
        )
        # 4) 解析响应：有 tool_calls → 解析成 ToolCall 列表；否则 → 纯文本
        message = resp.choices[0].message
        reasoning = getattr(message, "reasoning_content", None) or None
        if getattr(message, "tool_calls", None):
            calls = []
            for tc in message.tool_calls:
                fn = tc.function
                # arguments 是 JSON 字符串，必须 json.loads 还原成参数字典；
                # 解析失败兜底为空参数字典（工具层会给出"参数不匹配"错误）
                try:
                    args = json.loads(fn.arguments) if fn.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                calls.append(ToolCall(name=fn.name, args=args, id=tc.id))
            return LLMResponse(content=None, tool_calls=calls, reasoning=reasoning)
        return LLMResponse(content=message.content, tool_calls=None, reasoning=reasoning)

    @staticmethod
    def _to_openai_messages(messages: list[dict]) -> list[dict]:
        """内部消息历史 → OpenAI 兼容消息列表。

        内部结构              →  OpenAI 结构
        user / 普通 assistant  →  原样透传
        assistant(tool_calls)  →  {role, content, tool_calls:[{id, type:"function", function:{name, arguments}}]}
        tool                   →  {role:"tool", tool_call_id, content}（id 回显"订单号"）
        """
        out = []
        for msg in messages:
            role = msg.get("role")
            if role == "assistant" and msg.get("tool_calls"):
                # assistant 决策消息：tool_calls 转 OpenAI 形状（arguments 已是 JSON 字符串）
                out.append({
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"]},
                        }
                        for tc in msg["tool_calls"]
                    ],
                })
            elif role == "tool":
                # 工具结果消息：必须带 tool_call_id 回显，且指向决策消息里的同一个 id
                out.append({
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", ""),
                    "content": msg.get("content", ""),
                })
            else:
                # user / 普通 assistant：直接透传
                out.append({"role": role, "content": msg.get("content", "")})
        return out

    @staticmethod
    def _to_tool_schema(tool) -> dict:
        """工具注册项 → OpenAI function schema（parameters 本身就是 JSON Schema）。"""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }


class MockLLM(LLMClient):
    """规则式 LLM：命中触发词则返回工具调用，否则返回规则回复。

    模拟真实 LLM 的循环行为：上一轮刚执行完工具时，总结工具结果给出
    最终回复并停止继续调用工具，避免无限工具循环。
    """

    def init(self) -> None:
        pass

    # 指代词：新问答含这些词时，视为承接上文的省略表达，需用最近消息补全
    _REFERENTIAL = ("那", "这个", "这", "它", "他", "她", "其", "它们")

    def generate(self, messages: list[dict]) -> LLMResponse:
        # 记忆提取任务（⑦）：system 含"长期记忆提取器"标记 → 走规则提取分支。
        # 必须放在工具路由之前：提取 prompt 里可能含"天气/计算"等触发词，不能误路由工具。
        system_text = next(
            (str(m.get("content", "")) for m in messages if m.get("role") == "system"),
            "",
        )
        if "长期记忆提取器" in system_text:
            user_text = next(
                (str(m.get("content", "")) for m in messages if m.get("role") == "user"),
                "",
            )
            return LLMResponse(
                content=self._extract_memories(user_text),
                tool_calls=None,
                reasoning="这是长期记忆提取任务，按规则从对话中提取自包含事实。",
            )
        last = messages[-1] if messages else {}
        if last.get("role") == "tool":
            # 工具刚执行完：模拟 LLM 基于工具结果生成最终回复
            content = str(last.get("content", ""))
            return LLMResponse(
                content=f"好的，{content}",
                tool_calls=None,
                reasoning=f"已拿到工具返回「{content}」，据此组织最终回复。",
            )
        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = str(msg.get("content", ""))
                break
        tool_name = route(last_user)
        if tool_name:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(name=tool_name, args=extract_args(tool_name, last_user))],
                reasoning=f"用户请求「{last_user}」涉及{tool_name}，需要调用工具获取结果。",
            )
        return LLMResponse(
            content=self._plain_reply(last_user),
            tool_calls=None,
            reasoning=f"用户请求「{last_user}」无需工具调用，直接组织文本回复。",
        )

    async def async_generate(self, messages: list[dict]) -> LLMResponse:
        # 记忆提取任务（⑦）：与 generate 同一规则分支
        system_text = next(
            (str(m.get("content", "")) for m in messages if m.get("role") == "system"),
            "",
        )
        if "长期记忆提取器" in system_text:
            user_text = next(
                (str(m.get("content", "")) for m in messages if m.get("role") == "user"),
                "",
            )
            return LLMResponse(
                content=self._extract_memories(user_text),
                tool_calls=None,
                reasoning="这是长期记忆提取任务，按规则从对话中提取自包含事实。",
            )
        last = messages[-1] if messages else {}
        if last.get("role") == "tool":
            # 工具刚执行完：模拟 LLM 基于工具结果生成最终回复
            content = str(last.get("content", ""))
            return LLMResponse(
                content=f"好的，{content}",
                tool_calls=None,
                reasoning=f"已拿到工具返回「{content}」，据此组织最终回复。",
            )
        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = str(msg.get("content", ""))
                break
        tool_name = route(last_user)
        if tool_name:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(name=tool_name, args=extract_args(tool_name, last_user))],
                reasoning=f"用户请求「{last_user}」涉及{tool_name}，需要调用工具获取结果。",
            )
        return LLMResponse(
            content=self._plain_reply(last_user),
            tool_calls=None,
            reasoning=f"用户请求「{last_user}」无需工具调用，直接组织文本回复。",
        )

    @staticmethod
    def _plain_reply(query: str) -> str:
        q = query.strip()
        if not q:
            return "请告诉我你想做什么，例如：计算 1+2*3、搜索 RAG、北京天气。"
        greetings = ("你好", "hi", "hello", "嗨", "在吗", "哈喽")
        if q.lower().startswith(greetings) or any(g in q.lower() for g in greetings):
            return "你好！我可以帮你计算、搜索知识库或查询天气，例如「计算 1+2*3」「搜索 RAG」「北京天气」。"
        return f"我收到了：{q}（当前为 Mock 模式，未接入真实大模型）"

    # ---- 长期记忆提取（⑦）：规则近似 mem0 的 LLM 提取，输出 {"facts": [...]} ----

    @classmethod
    def _extract_memories(cls, user_text: str) -> str:
        """按提取 prompt 的段落结构解析输入，产出自包含事实 JSON。

        规则（笔试规模的可测近似，真实 LLM 由提示词完成同一语义）：
        1. 新问答含指代词（那/这个/它…）且最近消息有内容 → 用最近一条消息补全主题，
           避免存成孤立片段（如"那南昌呢"补全为"北京天气…；南昌多云 20 度"）；
        2. 否则取本轮回复作为事实；
        3. 输出 {"facts": [...]}（与真实 LLM 同格式，提取器解析路径一致）。
        """
        existing_block = cls._slice(user_text, "## Existing Memories", "## Last k Messages")
        recent_block = cls._slice(user_text, "## Last k Messages", "## New Messages")
        new_block = cls._slice(user_text, "## New Messages", None)
        # 解析新问答：形如 "Q: ...\nA: ..."
        answer = ""
        question = ""
        for line in new_block.splitlines():
            if line.startswith("Q:"):
                question = line[2:].strip()
            elif line.startswith("A:"):
                answer = line[2:].strip()
        facts: list[str] = []
        # 指代消解：问句含指代词且最近消息非空 → 上下文补全
        if question and any(t in question for t in cls._REFERENTIAL) and recent_block.strip():
            topic = recent_block.strip().splitlines()[0].strip()  # 最近一条消息首行
            facts.append(f"{topic}；{answer}")
        elif answer.strip():
            facts.append(answer.strip())
        # existing_block 仅作参考（真实 LLM 用它判重/合并；Mock 简化不判重，
        # 去重由 BM25Memory.remember 的 md5 统一负责）
        return json.dumps({"facts": facts}, ensure_ascii=False)

    @staticmethod
    def _slice(text: str, start: str, end: str | None) -> str:
        """按段落标记切出 section 文本（找不到返回空串）。"""
        s = text.find(start)
        if s == -1:
            return ""
        s += len(start)
        e = len(text) if end is None else text.find(end, s)
        if e == -1:
            e = len(text)
        return text[s:e].strip()
