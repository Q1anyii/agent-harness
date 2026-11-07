"""Agent 运行时：自实现类 LangGraph 的最小循环（状态机 + 工具调用 + 轮次限制）。"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass

from agent.constants import MAX_CONTEXT_TOKENS, MAX_ROUNDS, MEMORY_RECALL_K
from agent.context import build_system_prompt, trim_messages
from agent.events import EventQueue
from agent.llm import LLMClient, LLMResponse
from agent.memory import MemoryExtractor, MemoryStrategy
from agent.session import Session, SessionBusyError
from agent.tools import get_all_tools, get_tool


@dataclass
class AgentResult:
    reply: str
    trace: list[dict]
    rounds_used: int  # 工具调用次数：最近一条 user 消息之后实际执行的工具条数
    max_rounds: int


class AgentRuntime:
    """最小循环：

    Step1 接收用户输入
    Step2 LLM 判断直接回复 or 调用工具
    Step3 调用工具
    Step4 根据工具结果判断继续 loop 还是返回给用户
    """

    def __init__(self, llm: LLMClient, max_rounds: int = MAX_ROUNDS,
                 max_context_tokens: int = MAX_CONTEXT_TOKENS,
                 queue: EventQueue | None = None,
                 memory: MemoryStrategy | None = None,
                 memory_recall_k: int = MEMORY_RECALL_K,
                 memory_extractor: MemoryExtractor | None = None) -> None:
        self.llm = llm
        self.max_rounds = max_rounds
        # context 窗口上限：估算 token 超限时从最旧裁剪（见 agent/context.py）
        self.max_context_tokens = max_context_tokens
        # 流式事件队列：传入则生成过程事件（reasoning/工具调用/回复增量）实时入队，
        # 前端轮询消费；不传则静默跳过（既有 sync 测试零影响）
        self.queue = queue
        # 长期记忆（⑦）：传入则每轮 QA 落库 + 本轮提问召回 top-k 拼入 system。
        # 默认 None：不配即无记忆（既有测试零影响），插件化策略可换实现。
        self.memory = memory
        self.memory_recall_k = memory_recall_k
        # 落库层 LLM 提取器（⑦）：配置后每轮 QA 先经 LLM 提取自包含事实再落库，
        # 指代（"那南昌呢"承接上文）由提取上下文消解；不配则直接存原始 QA。
        self.memory_extractor = memory_extractor

    def _build_messages(self, session: Session, user_content: str) -> list[dict]:
        """构造发给 LLM 的消息列表：system prompt（会话级，首次构造后复用）
        + 长期记忆召回段（每轮动态）+ 对话历史 + 本轮 user 提问，最后做窗口裁剪。"""
        messages: list[dict] = list(session.messages)
        # system prompt：会话开始时构造一次（含可用工具与当前时间），之后复用
        if not session.system_prompt:
            session.system_prompt = build_system_prompt(
                [t.name for t in get_all_tools()]
            )
        system = session.system_prompt
        # 长期记忆召回（⑦）：以当前提问为 query 检索 top-k 相关记忆，
        # 拼入"本次请求"的 system（动态段，不写回缓存的 session.system_prompt）。
        # 短期窗口裁掉的历史信息可经此召回，形成"短期窗口 + 长期记忆"闭环。
        if self.memory:
            hits = self.memory.recall(user_content, k=self.memory_recall_k, session_id=session.session_id)
            if hits:
                memories_text = "\n".join(f"- {e.content}" for e in hits)
                system += "\n\n【长期记忆（历史问答，仅供参考）】\n" + memories_text
        messages.insert(0, {"role": "system", "content": system})
        messages.append({"role": "user", "content": user_content})
        # 上下文膨胀压缩：保留 system + 最近消息，最后一条 user 无条件保留
        return trim_messages(messages, self.max_context_tokens)

    def run(self, session: Session, user_content: str) -> AgentResult:
        # 0) 会话忙时拒绝新消息，避免并发覆盖状态（对应架构题模块四第 2 问）
        if session.state != "idle":
            raise SessionBusyError("会话正忙，请等上一条消息处理完成")
        session.state = "busy"
        try:
            # 1) 复制会话历史（不污染原列表），并把本轮用户输入追加为 user 消息
            messages: list[dict] = self._build_messages(session, user_content)
            trace: list[dict] = []

            # 2) 最多循环 max_rounds 轮：每轮让 LLM 决策"直接回复 or 调用工具"
            last_reasoning: str | None = None
            for _ in range(self.max_rounds):
                response: LLMResponse = self.llm.generate(messages)
                # 记录本轮思考过程：最终回复消息会带上最后一轮的 reasoning（落库供前端穿插渲染）
                if response.reasoning:
                    last_reasoning = response.reasoning
                # 2a) 思考过程事件：LLM 返回 reasoning 时实时入队（⑥ 前端显示思考过程）
                if self.queue and response.reasoning:
                    self.queue.publish(session.session_id, {
                        "type": "reasoning", "content": response.reasoning,
                    })
                if response.tool_calls:
                    # 3a) LLM 决定调用工具 → 先把"决策消息"记入历史：
                    #     一条 assistant 消息，tool_calls 是 OpenAI 兼容形状的纯 dict 列表，
                    #     每条调用分配唯一 id（ToolCall.id 为空时用 uuid 兜底）。
                    #     arguments 必须是 JSON 字符串（协议要求），工具参数 dict 用 json.dumps 序列化。
                    #     reasoning 一并落库：刷新全量后思考过程不丢，前端按时间序穿插渲染（⑥）。
                    decision = {
                        "role": "assistant",
                        "content": None,
                        "reasoning": response.reasoning,
                        "tool_calls": [
                            {
                                "id": call.id or f"call_{uuid.uuid4().hex[:12]}",
                                "name": call.name,
                                "arguments": json.dumps(call.args, ensure_ascii=False),
                            }
                            for call in response.tool_calls
                        ],
                    }
                    messages.append(decision)

                    # 3b) 逐条执行工具：结果以 tool 消息回填，tool_call_id 必须与决策消息中的 id 同源
                    #     （"订单号"：API 靠它把结果挂到那一次调用上，zip 保证一一对应）。
                    for call, tc in zip(response.tool_calls, decision["tool_calls"]):
                        # 工具调用事件（② 前端 AI 消息块内的工具子组件）
                        if self.queue:
                            self.queue.publish(session.session_id, {
                                "type": "tool_call", "id": tc["id"],
                                "name": call.name, "args": call.args,
                            })
                        item = self._execute_tool(call.name, call.args)
                        trace.append(item)
                        # 工具结果事件：与 tool_call 同 id 配对
                        if self.queue:
                            self.queue.publish(session.session_id, {
                                "type": "tool_result", "id": tc["id"],
                                "name": call.name, "result": item["result"],
                                "status": item["status"], "duration_ms": item["duration_ms"],
                            })
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "name": call.name,
                                "content": item["result"],
                            }
                        )
                    continue  # 3c) 工具结果已放回上下文，进入下一轮让 LLM 总结或继续调用
                # 4) LLM 直接给出最终回复：跳出循环
                reply = response.content
                break
            else:
                # 5) 达到轮次上限仍未结束：终止并提示（不阻塞后续会话）
                reply = f"已达到单次问答工具调用轮次上限（{self.max_rounds} 轮），已终止本次执行。"

            # 5a) 流式输出：最终回复切成增量块入队（前端逐块渲染，done 标记收尾）
            self._publish_reply(session.session_id, reply)

            # 5b) 长期记忆落库（⑦）：有提取器则 LLM 提取自包含事实后逐条落库，
            #     否则直接存原始 QA。短期窗口裁掉的信息可经召回重新进入上下文。
            self._remember_round(session, user_content, reply)

            # 6) 把最终回复追加为 assistant 消息并写回会话（历史持久化到 session）
            #    system prompt 是运行时注入的上下文，不写入对话历史（存储保持干净）
            #    带上最后一轮 reasoning：思考过程随最终回复一并落库（⑥ 全量刷新后仍在）
            reply_msg: dict = {"role": "assistant", "content": reply}
            if last_reasoning:
                reply_msg["reasoning"] = last_reasoning
            messages.append(reply_msg)
            session.messages = [m for m in messages if m.get("role") != "system"]
            session.traces.extend(trace)

            # 7) 工具调用次数 = 最近一条 user 消息之后出现的 tool 消息数，
            #    即本次问答实际执行的工具条数（历史会话中的工具调用不计入）。
            last_user_idx = max(i for i, m in enumerate(messages) if m.get("role") == "user")
            tool_calls_used = sum(
                1 for m in messages[last_user_idx + 1:] if m.get("role") == "tool"
            )
            return AgentResult(
                reply=reply,
                trace=trace,
                rounds_used=tool_calls_used,
                max_rounds=self.max_rounds,
            )
        finally:
            # 8) 无论成功失败都复位会话状态，保证会话可复用
            session.state = "idle"

    async def async_run(self, session: Session, user_content: str) -> AgentResult:
        # 0) 会话忙时拒绝新消息，避免并发覆盖状态（对应架构题模块四第 2 问）
        if session.state != "idle":
            raise SessionBusyError("会话正忙，请等上一条消息处理完成")
        session.state = "busy"
        try:
            # 1) 复制会话历史（不污染原列表），并把本轮用户输入追加为 user 消息
            messages: list[dict] = self._build_messages(session, user_content)
            trace: list[dict] = []

            # 2) 最多循环 max_rounds 轮：每轮让 LLM 决策"直接回复 or 调用工具"
            last_reasoning: str | None = None
            for _ in range(self.max_rounds):
                response: LLMResponse = await self.llm.async_generate(messages)
                # 记录本轮思考过程：最终回复消息会带上最后一轮的 reasoning（落库供前端穿插渲染）
                if response.reasoning:
                    last_reasoning = response.reasoning
                # 2a) 思考过程事件：LLM 返回 reasoning 时实时入队（⑥ 前端显示思考过程）
                if self.queue and response.reasoning:
                    self.queue.publish(session.session_id, {
                        "type": "reasoning", "content": response.reasoning,
                    })
                if response.tool_calls:
                    # 3a) LLM 决定调用工具 → 先把"决策消息"记入历史：
                    #     一条 assistant 消息，tool_calls 是 OpenAI 兼容形状的纯 dict 列表，
                    #     每条调用分配唯一 id（ToolCall.id 为空时用 uuid 兜底）。
                    #     arguments 必须是 JSON 字符串（协议要求），工具参数 dict 用 json.dumps 序列化。
                    #     reasoning 一并落库：刷新全量后思考过程不丢，前端按时间序穿插渲染（⑥）。
                    decision = {
                        "role": "assistant",
                        "content": None,
                        "reasoning": response.reasoning,
                        "tool_calls": [
                            {
                                "id": call.id or f"call_{uuid.uuid4().hex[:12]}",
                                "name": call.name,
                                "arguments": json.dumps(call.args, ensure_ascii=False),
                            }
                            for call in response.tool_calls
                        ],
                    }
                    messages.append(decision)

                    # 3b) 逐条执行工具：结果以 tool 消息回填，tool_call_id 必须与决策消息中的 id 同源
                    #     （"订单号"：API 靠它把结果挂到那一次调用上，zip 保证一一对应）。
                    for call, tc in zip(response.tool_calls, decision["tool_calls"]):
                        # 工具调用事件（② 前端 AI 消息块内的工具子组件）
                        if self.queue:
                            self.queue.publish(session.session_id, {
                                "type": "tool_call", "id": tc["id"],
                                "name": call.name, "args": call.args,
                            })
                        item = await asyncio.to_thread(self._execute_tool, call.name, call.args)
                        trace.append(item)
                        # 工具结果事件：与 tool_call 同 id 配对
                        if self.queue:
                            self.queue.publish(session.session_id, {
                                "type": "tool_result", "id": tc["id"],
                                "name": call.name, "result": item["result"],
                                "status": item["status"], "duration_ms": item["duration_ms"],
                            })
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "name": call.name,
                                "content": item["result"],
                            }
                        )
                    continue  # 3c) 工具结果已放回上下文，进入下一轮让 LLM 总结或继续调用
                # 4) LLM 直接给出最终回复：跳出循环
                reply = response.content
                break
            else:
                # 5) 达到轮次上限仍未结束：终止并提示（不阻塞后续会话）
                reply = f"已达到单次问答工具调用轮次上限（{self.max_rounds} 轮），已终止本次执行。"

            # 5a) 流式输出：最终回复切成增量块入队（前端逐块渲染，done 标记收尾）
            self._publish_reply(session.session_id, reply)

            # 5b) 长期记忆落库（⑦）：有提取器则 LLM 提取自包含事实后逐条落库，
            #     否则直接存原始 QA。短期窗口裁掉的信息可经召回重新进入上下文。
            await asyncio.to_thread(self._remember_round, session, user_content, reply)

            # 6) 把最终回复追加为 assistant 消息并写回会话（历史持久化到 session）
            #    system prompt 是运行时注入的上下文，不写入对话历史（存储保持干净）
            #    带上最后一轮 reasoning：思考过程随最终回复一并落库（⑥ 全量刷新后仍在）
            reply_msg: dict = {"role": "assistant", "content": reply}
            if last_reasoning:
                reply_msg["reasoning"] = last_reasoning
            messages.append(reply_msg)
            session.messages = [m for m in messages if m.get("role") != "system"]
            session.traces.extend(trace)

            # 7) 工具调用次数 = 最近一条 user 消息之后出现的 tool 消息数，
            #    即本次问答实际执行的工具条数（历史会话中的工具调用不计入）。
            last_user_idx = max(i for i, m in enumerate(messages) if m.get("role") == "user")
            tool_calls_used = sum(
                1 for m in messages[last_user_idx + 1:] if m.get("role") == "tool"
            )
            return AgentResult(
                reply=reply,
                trace=trace,
                rounds_used=tool_calls_used,
                max_rounds=self.max_rounds,
            )
        finally:
            # 8) 无论成功失败都复位会话状态，保证会话可复用
            session.state = "idle"

    @staticmethod
    def _chunk_text(text: str, size: int = 24) -> list[str]:
        """把完整回复切成固定大小的增量块（模拟流式传输）。"""
        return [text[i:i + size] for i in range(0, len(text), size)] or [""]

    def _publish_reply(self, session_id: str, reply: str) -> None:
        """流式输出：最终回复切块入队（done 标记最后一块）。

        当前是"切块模拟流式"；真实逐 token 流后续可在 LLMClient 加 stream 接口
        后改为边生成边入队，EventQueue 抽象与前端轮询无需改动。
        """
        if not self.queue:
            return
        chunks = self._chunk_text(reply)
        for i, chunk in enumerate(chunks):
            self.queue.publish(session_id, {
                "type": "message_delta",
                "delta": chunk,
                "done": i == len(chunks) - 1,
            })

    def _remember_round(self, session: Session, user_content: str, reply: str) -> None:
        """长期记忆落库（⑦）：LLM 提取自包含事实后逐条落库。

        写入管线对齐 mem0（MEM0_DEEP_DIVE.md §1）：
        - P1 已有记忆：以本轮提问召回相关记忆，供提取器判重/合并参考（防幻觉）；
        - P0 最近消息：最近 k 条历史消息进提取上下文，消解指代（"那南昌呢"承接上文）；
        - P2 LLM 提取：从「已有记忆 + 最近消息 + 本轮 QA」提取自包含事实；
        - P4/P5 去重：BM25Memory.remember 内 md5 去重，完全重复不重复入库。
        未配置提取器时直接存原始 QA（兼容既有行为）。
        """
        if not self.memory:
            return
        qa = f"Q: {user_content}\nA: {reply}"
        if self.memory_extractor is None:
            self.memory.remember(session.session_id, qa)
            return
        existing = self.memory.recall(
            user_content, k=5, session_id=session.session_id
        )
        recent = [
            str(m.get("content", ""))
            for m in session.messages[-self.memory_extractor.recent_k:]
            if m.get("content")
        ]
        facts = self.memory_extractor.extract(existing, qa, recent)
        for fact in facts:
            self.memory.remember(session.session_id, fact)

    @staticmethod
    def _execute_tool(name: str, args: dict[str, str]) -> dict:
        """执行单个工具：异常兜底 + 耗时记录。"""
        start = time.perf_counter()
        tool = get_tool(name)
        try:
            if tool is None:
                result, status = f"错误：未知工具「{name}」", "error"
            else:
                # 工具 handler 是 Callable，**args 展开参数字典后直接调用
                result, status = str(tool.handler(**args)), "success"
        except TypeError as e:
            # 参数不匹配（缺参/多参/类型错）→ 记 error，不阻断循环
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
