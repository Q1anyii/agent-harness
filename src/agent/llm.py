"""LLM 抽象与 Mock 实现。

最小闭环阶段使用 MockLLM（规则式）：无需 API Key 即可跑通前后端联调。
真实大模型接入（OpenAI-compatible chat/completions）留待后续迭代，
接入点即 LLMClient.generate()。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from agent.router import extract_args, route
from dotenv import load_dotenv
import os


load_dotenv(override=True)

@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
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


class DeepSeekLLM(LLMClient):

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None): 
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.client = None
        
    def init(self) -> DeepSeekLLM:          # 读环境变量/缺省值 → self.client = OpenAI(...)
        from openai import OpenAI
        self.api_key = self.api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.base_url = self.base_url or os.environ.get(
            "BASE_URL", "https://api.deepseek.com"
        )
        self.model = self.model or os.environ.get("MODEL_NAME", "deepseek-flash")

        # 3) 快速失败：key 缺失立刻报错，而不是让 OpenAI 库深层报错
        if not self.api_key:
            raise ValueError("缺少 DEEPSEEK_API_KEY：请在 .env 配置或传入 api_key")

        # 4) 真正创建客户端
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=60.0)
        return self
        
    def generate(self, messages: list[dict]) -> LLMResponse:
        resp = self.client.chat.completions.create(
            model = self.model,
            messages = messages,
        )
        return LLMResponse(content=resp.choices[0].message.content, tool_calls=None)


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

    @staticmethod
    def _plain_reply(query: str) -> str:
        q = query.strip()
        if not q:
            return "请告诉我你想做什么，例如：计算 1+2*3、搜索 RAG、北京天气。"
        greetings = ("你好", "hi", "hello", "嗨", "在吗", "哈喽")
        if q.lower().startswith(greetings) or any(g in q.lower() for g in greetings):
            return "你好！我可以帮你计算、搜索知识库或查询天气，例如「计算 1+2*3」「搜索 RAG」「北京天气」。"
        return f"我收到了：{q}（当前为 Mock 模式，未接入真实大模型）"
