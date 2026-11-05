"""DeepSeekLLM 单元测试：伪造 OpenAI client，不联网、不用真 key。

覆盖：纯文本响应 / 单工具调用 / 多工具调用 / malformed arguments 兜底 /
消息格式转换（tool_call_id 回显）/ tools schema 下发 / 与 runtime 联动的"订单号同源"。
"""
from __future__ import annotations

import pytest

from agent.llm import DeepSeekLLM, LLMClient, LLMResponse, ToolCall
from agent.runtime import AgentRuntime
from agent.session import SessionManager


# ---------- 伪造 OpenAI client（模拟 chat.completions.create 的返回结构） ----------

class FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, id: str, function: FakeFunction) -> None:
        self.id = id
        self.function = function


class FakeMessage:
    def __init__(self, content=None, tool_calls=None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, message: FakeMessage) -> None:
        self.message = message


class FakeResponse:
    def __init__(self, message: FakeMessage) -> None:
        self.choices = [FakeChoice(message)]


class FakeCompletions:
    """记录每次 create 的入参，并按响应队列依次返回。"""

    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeChat:
    def __init__(self, *responses: FakeResponse) -> None:
        self.completions = FakeCompletions(*responses)


class FakeClient:
    def __init__(self, *responses: FakeResponse) -> None:
        self.chat = FakeChat(*responses)


def _make_llm(*responses: FakeResponse) -> DeepSeekLLM:
    """构造注入 fake client 的 DeepSeekLLM（不走 init()，不联网、不用真 key）。"""
    llm = DeepSeekLLM(model="test-model")
    llm.client = FakeClient(*responses)
    return llm


# ---------- 纯文本响应 ----------

def test_generate_plain_text():
    """模型直接回复时：content 透传、tool_calls 为 None，且 create 入参正确。"""
    llm = _make_llm(FakeResponse(FakeMessage(content="你好！")))
    result = llm.generate([{"role": "user", "content": "hi"}])
    assert result.content == "你好！"
    assert result.tool_calls is None
    # create 入参：model / messages / tools 都正确下发
    call = llm.client.chat.completions.calls[0]
    assert call["model"] == "test-model"
    assert call["messages"] == [{"role": "user", "content": "hi"}]
    assert len(call["tools"]) == 4  # calculator / search / todo / weather


# ---------- 工具调用解析 ----------

def test_generate_single_tool_call():
    """arguments 是 JSON 字符串，json.loads 后还原成参数字典并保留 id。"""
    fn = FakeFunction("calculator", '{"expression": "1+1"}')
    msg = FakeMessage(content=None, tool_calls=[FakeToolCall("call_1", fn)])
    llm = _make_llm(FakeResponse(msg))
    result = llm.generate([{"role": "user", "content": "算 1+1"}])
    assert result.content is None
    assert result.tool_calls == [
        ToolCall(name="calculator", args={"expression": "1+1"}, id="call_1")
    ]


def test_generate_multi_tool_calls():
    """一次决策返回多个工具调用时，全部解析为 ToolCall 列表。"""
    calls = [
        FakeToolCall("call_1", FakeFunction("calculator", '{"expression": "1+1"}')),
        FakeToolCall("call_2", FakeFunction("weather", '{"city": "北京"}')),
    ]
    llm = _make_llm(FakeResponse(FakeMessage(content=None, tool_calls=calls)))
    result = llm.generate([{"role": "user", "content": "算 1+1 并查北京天气"}])
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0] == ToolCall(
        name="calculator", args={"expression": "1+1"}, id="call_1"
    )
    assert result.tool_calls[1] == ToolCall(
        name="weather", args={"city": "北京"}, id="call_2"
    )


def test_generate_malformed_arguments_falls_back_to_empty():
    """arguments 不是合法 JSON 时兜底为空字典，不让解析崩溃（工具层再兜底报错）。"""
    fn = FakeFunction("calculator", "{not-json")
    msg = FakeMessage(content=None, tool_calls=[FakeToolCall("call_1", fn)])
    llm = _make_llm(FakeResponse(msg))
    result = llm.generate([{"role": "user", "content": "算一下"}])
    assert result.tool_calls[0].args == {}


def test_generate_raises_on_api_error():
    """API 调用失败时异常向上抛，由调用方（main 层）决定如何呈现。"""
    llm = _make_llm(FakeResponse(FakeMessage(content="x")))

    class Boom(Exception):
        pass

    completions = llm.client.chat.completions
    completions.responses = []
    completions.create = lambda **kw: (_ for _ in ()).throw(Boom("api down"))
    with pytest.raises(Boom):
        llm.generate([{"role": "user", "content": "hi"}])


# ---------- 消息格式转换 ----------

def test_to_openai_messages_conversion():
    """内部历史 → OpenAI 格式：三种分支都转对，tool_call_id 回显订单号。"""
    internal = [
        {"role": "user", "content": "算 1+1"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_abc", "name": "calculator", "arguments": '{"expression": "1+1"}'}]},
        {"role": "tool", "tool_call_id": "call_abc", "name": "calculator", "content": "2.0"},
        {"role": "assistant", "content": "结果是 2.0"},
    ]
    out = DeepSeekLLM._to_openai_messages(internal)
    # user / 普通 assistant 直接透传
    assert out[0] == {"role": "user", "content": "算 1+1"}
    assert out[3] == {"role": "assistant", "content": "结果是 2.0"}
    # assistant 决策消息 → OpenAI tool_calls 形状（type/function 包裹）
    assert out[1]["tool_calls"][0] == {
        "id": "call_abc",
        "type": "function",
        "function": {"name": "calculator", "arguments": '{"expression": "1+1"}'},
    }
    # tool 消息 → tool_call_id 回显
    assert out[2] == {"role": "tool", "tool_call_id": "call_abc", "content": "2.0"}


# ---------- tools schema 下发 ----------

def test_generate_passes_tools_schema():
    """tools 参数按注册表生成，每个工具都有 name/description/parameters。"""
    llm = _make_llm(FakeResponse(FakeMessage(content="ok")))
    llm.generate([{"role": "user", "content": "hi"}])
    tools = llm.client.chat.completions.calls[0]["tools"]
    assert all(t["type"] == "function" for t in tools)
    names = [t["function"]["name"] for t in tools]
    assert names == ["calculator", "search", "todo", "weather"]
    calc = next(t for t in tools if t["function"]["name"] == "calculator")
    assert "description" in calc["function"]
    assert "parameters" in calc["function"]


# ---------- 与 runtime 联动：订单号同源 ----------

def test_runtime_tool_call_id_matching():
    """真实数据流：assistant 决策消息与 tool 消息的 id 必须同源，
    且发往 API 的消息是 OpenAI 兼容形状。"""
    first = FakeMessage(content=None, tool_calls=[
        FakeToolCall("call_abc", FakeFunction("calculator", '{"expression": "1+1"}'))])
    second = FakeMessage(content="结果是 2.0", tool_calls=None)
    llm = _make_llm(FakeResponse(first), FakeResponse(second))

    mgr = SessionManager()
    s = mgr.create()
    result = AgentRuntime(llm=llm).run(s, "算 1+1")
    assert result.reply == "结果是 2.0"
    assert result.rounds_used == 1

    # 会话历史里：决策消息与 tool 消息 id 同源
    decision = next(m for m in s.messages if m.get("role") == "assistant" and m.get("tool_calls"))
    tool_msg = next(m for m in s.messages if m.get("role") == "tool")
    assert decision["tool_calls"][0]["id"] == tool_msg["tool_call_id"] == "call_abc"

    # 第二次调用（带工具结果）发往 API 的消息必须是 OpenAI 形状。
    # 注：runtime 现注入 system prompt（消息首条），故按角色语义定位而非固定索引。
    sent = llm.client.chat.completions.calls[1]["messages"]
    decision_msg = next(m for m in sent if m.get("role") == "assistant" and m.get("tool_calls"))
    tool_msg = next(m for m in sent if m.get("role") == "tool")
    assert decision_msg["tool_calls"][0]["id"] == "call_abc"
    assert decision_msg["tool_calls"][0]["type"] == "function"
    # tool 消息回显同一订单号（content 是工具真实输出，这里只验证 id 与角色）
    assert tool_msg["tool_call_id"] == "call_abc"


def test_runtime_uuid_fallback_for_no_id():
    """ToolCall.id 为空（Mock/MultiToolLLM 路径）时 runtime 用 uuid 兜底，id 仍同源。"""

    class NoIdLLM(LLMClient):
        """第一次决策返回无 id 的 ToolCall，第二次返回总结。"""

        def init(self) -> None:
            return None

        def generate(self, messages: list[dict]) -> LLMResponse:
            if not getattr(self, "_done", False):
                self._done = True
                return LLMResponse(
                    content=None,
                    tool_calls=[ToolCall(name="calculator", args={"expression": "1+1"})],
                )
            return LLMResponse(content="完成", tool_calls=None)

        # async 抽象方法契约：纯 sync 逻辑（无 IO），直接复用 generate 即可
        async def async_generate(self, messages: list[dict]) -> LLMResponse:
            return self.generate(messages)

    mgr = SessionManager()
    s = mgr.create()
    result = AgentRuntime(llm=NoIdLLM()).run(s, "算 1+1")
    decision = next(m for m in s.messages if m.get("role") == "assistant" and m.get("tool_calls"))
    tool_msg = next(m for m in s.messages if m.get("role") == "tool")
    assert decision["tool_calls"][0]["id"].startswith("call_")
    assert decision["tool_calls"][0]["id"] == tool_msg["tool_call_id"]
    assert result.rounds_used == 1
