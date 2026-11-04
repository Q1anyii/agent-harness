"""Agent 运行时：自实现类 LangGraph 的最小循环（状态机 + 工具调用 + 轮次限制）。"""
from __future__ import annotations

import time
from dataclasses import dataclass

from agent.llm import LLMClient, LLMResponse
from agent.session import Session, SessionBusyError
from agent.tools import get_tool


@dataclass
class AgentResult:
    reply: str
    trace: list[dict]
    rounds_used: int
    max_rounds: int


class AgentRuntime:
    """最小循环：

    Step1 接收用户输入
    Step2 LLM 判断直接回复 or 调用工具
    Step3 调用工具
    Step4 根据工具结果判断继续 loop 还是返回给用户
    """

    def __init__(self, llm: LLMClient, max_rounds: int = 8) -> None:
        self.llm = llm
        self.max_rounds = max_rounds

    def run(self, session: Session, user_content: str) -> AgentResult:
        if session.state != "idle":
            raise SessionBusyError("会话正忙，请等上一条消息处理完成")
        session.state = "busy"
        try:
            messages: list[dict] = list(session.messages)
            messages.append({"role": "user", "content": user_content})
            trace: list[dict] = []
            rounds_used = 0

            for _ in range(self.max_rounds):
                response: LLMResponse = self.llm.generate(messages)
                if response.tool_calls:
                    rounds_used += 1
                    for call in response.tool_calls:
                        item = self._execute_tool(call.name, call.args)
                        trace.append(item)
                        messages.append(
                            {"role": "tool", "name": call.name, "content": item["result"]}
                        )
                    continue  # 工具结果放回上下文，继续 loop
                reply = response.content
                break
            else:
                reply = f"已达到单次问答工具调用轮次上限（{self.max_rounds} 轮），已终止本次执行。"

            messages.append({"role": "assistant", "content": reply})
            session.messages = messages
            session.traces.extend(trace)
            return AgentResult(
                reply=reply,
                trace=trace,
                rounds_used=rounds_used,
                max_rounds=self.max_rounds,
            )
        finally:
            session.state = "idle"

    @staticmethod
    def _execute_tool(name: str, args: dict[str, str]) -> dict:
        """执行单个工具：异常兜底 + 耗时记录。"""
        start = time.perf_counter()
        tool = get_tool(name)
        try:
            if tool is None:
                result, status = f"错误：未知工具「{name}」", "error"
            else:
                result, status = str(tool.handler(**args)), "success"
        except TypeError as e:
            result, status = f"错误：工具参数不匹配：{e}", "error"
        except Exception as e:  # noqa: BLE001 - 工具级兜底，不阻断循环
            result, status = f"错误：{type(e).__name__}: {e}", "error"
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "tool": name,
            "args": dict(args),
            "result": result,
            "status": status,
            "duration_ms": duration_ms,
        }
