# devlog：消息块穿插式渲染 + reasoning 落库修复

时间：2026-11-05 14:10
提交：`消息块：reasoning落库与工具调用穿插式渲染`（cade9cd）
范围：② trace 嵌入消息（穿插式）+ ⑥ reasoning（不丢失）

## 问题（用户反馈）

1. **工具调用盒子没有穿插式**：多轮工具调用时，所有思考被拼成一个折叠块、所有工具卡堆成一个列表，
   丢失了"思考 → 工具 → 思考 → 工具 → … → 回复"的时序结构。
2. **消息生成完毕后思考过程不见了**：reasoning 只进事件队列（流式实时显示），
   没有写回 session.messages → POST 返回后前端刷新全量消息，streaming 块被清空，思考过程就丢了。

## 根因

- runtime 构造 decision 消息（assistant + tool_calls）与最终回复消息时**没有带 reasoning 字段**；
  事件队列只负责"实时传输"，会话消息才是真相源，二者未打通。
- 前端 AiBlock 是"单块结构"（reasoning 一个 + toolCalls 一个列表 + content 一段），
  无法表达多轮穿插时序。

## 修复

**后端（src/agent/runtime.py）**
- 决策消息落库：`decision["reasoning"] = response.reasoning`（每轮决策的思考随消息持久化）。
- 总结消息落库：循环内记录 `last_reasoning`，最终回复消息带上最后一轮 reasoning。
- 发送侧无需改动：`_to_openai_messages` 本就"挑字段构造"，reasoning 不会回传给 OpenAI 兼容 API。

**前端（穿插式数据结构）**
- `types.ts`：ChatMessage 加 `reasoning`；AiBlock 从"单块"重构为 `segments: AiSegment[]`——
  段类型 `reasoning | tool | text`，按时间序排列。
- `App.tsx` applyEvents：事件按序追加段——reasoning 追加/合并思考段、tool_call 新工具段、
  tool_result 按 id 回填、message_delta 追加/合并末尾文本段 → 天然穿插。
- `ChatBox.tsx` buildRenderItems：历史消息聚合成同样结构——
  决策思考段 → 每个工具调用一个 tool 段（结果按 tool_call_id 回填）→ 总结思考段 → 回复文本段。
- `AiMessageBox.tsx`：按 segments 顺序渲染；打字机只作用于末尾文本段。

## 验证

- 新增 `test_reasoning_persisted_in_messages`：断言决策消息与总结消息都带 reasoning 且内容正确。
- 全量 **149 passed**（原 148 + 新 1）。
- 前端 tsc + vite build 通过。
- TestClient 实测 /messages 返回序列：
  `user → assistant(tool_calls=calculator, reasoning=用户请求…涉及calculator) → tool(结果) → assistant(回复, reasoning=已拿到工具返回…)`
  前端聚合后渲染为：思考段 → 工具卡 → 思考段 → 回复段（穿插式）。

## 待办

- 真实逐 token 流：LLMClient stream 接口（当前 message_delta 为切块模拟 + 前端打字机）。
- P1 ⑤ 中间件、⑦ 长期记忆（Mitta 路径待提供）；P2 ⑧ Docker、⑨ 收尾。
