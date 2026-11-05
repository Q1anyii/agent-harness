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
    """LLM 一次决策的结果：要么给文本回复（tool_calls=None），要么给工具调用列表（content=None）。"""

    content: str | None
    tool_calls: list[ToolCall] | None


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
        self.async_client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=60.0)
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=60.0)
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
        # 4) 解析响应：有 tool_calls → 解析成 ToolCall 列表；否则 → 纯文本
        message = resp.choices[0].message
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
            return LLMResponse(content=None, tool_calls=calls)
        return LLMResponse(content=message.content, tool_calls=None)

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
            return LLMResponse(content=None, tool_calls=calls)
        return LLMResponse(content=message.content, tool_calls=None)

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

    def generate(self, messages: list[dict]) -> LLMResponse:
        last = messages[-1] if messages else {}
        if last.get("role") == "tool":
            # 工具刚执行完：模拟 LLM 基于工具结果生成最终回复
            content = str(last.get("content", ""))
            return LLMResponse(content=f"好的，{content}", tool_calls=None)
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
            )
        return LLMResponse(content=self._plain_reply(last_user), tool_calls=None)

    async def async_generate(self, messages: list[dict]) -> LLMResponse:
        last = messages[-1] if messages else {}
        if last.get("role") == "tool":
            # 工具刚执行完：模拟 LLM 基于工具结果生成最终回复
            content = str(last.get("content", ""))
            return LLMResponse(content=f"好的，{content}", tool_calls=None)
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
            )
        return LLMResponse(content=self._plain_reply(last_user), tool_calls=None)

    @staticmethod
    def _plain_reply(query: str) -> str:
        q = query.strip()
        if not q:
            return "请告诉我你想做什么，例如：计算 1+2*3、搜索 RAG、北京天气。"
        greetings = ("你好", "hi", "hello", "嗨", "在吗", "哈喽")
        if q.lower().startswith(greetings) or any(g in q.lower() for g in greetings):
            return "你好！我可以帮你计算、搜索知识库或查询天气，例如「计算 1+2*3」「搜索 RAG」「北京天气」。"
        return f"我收到了：{q}（当前为 Mock 模式，未接入真实大模型）"
