// 与后端 OpenAPI 契约对应的前端类型定义

export interface SessionInfo {
  session_id: string
  created_at: string
  state: string
  message_count: number
}

// 后端消息：assistant 决策消息带 tool_calls（arguments 为 JSON 字符串），
// tool 消息用 tool_call_id 回显"订单号"配对
export interface ChatToolCall {
  id: string
  name: string
  arguments: string
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'tool'
  content: string | null
  name?: string
  tool_call_id?: string
  tool_calls?: ChatToolCall[]
  // 思考过程（⑥）：assistant 决策/总结消息落库带回，前端按时间序穿插渲染
  reasoning?: string | null
}

export interface TraceItem {
  tool: string
  args: Record<string, string>
  result: string
  status: string
  duration_ms: number
}

export interface ChatResult {
  session_id: string
  reply: string
  trace: TraceItem[]
  rounds_used: number
  max_rounds: number
}

// ---------- 流式事件（④）与 AI 消息块（②⑥） ----------

export type StreamEventType = 'reasoning' | 'tool_call' | 'tool_result' | 'message_delta'

export interface StreamEvent {
  seq: number
  type: StreamEventType
  // reasoning
  content?: string
  // tool_call / tool_result
  id?: string
  name?: string
  args?: Record<string, unknown>
  result?: string
  status?: string
  duration_ms?: number
  // message_delta
  delta?: string
  done?: boolean
}

export interface EventsResponse {
  session_id: string
  events: StreamEvent[]
  latest_seq: number
}

// AI 消息块内的单个工具调用（② 工具子组件数据）
export interface ToolCallBlock {
  id: string
  name: string
  args: Record<string, unknown>
  result?: string
  status?: string
  duration_ms?: number
}

// AI 消息块内的一个"段"（②⑥ 穿插式：按时间序 = 思考 → 工具 → 思考 → … → 最终回复）
export type AiSegmentType = 'reasoning' | 'tool' | 'text'

export interface AiSegment {
  type: AiSegmentType
  key: string
  reasoning?: string
  tool?: ToolCallBlock
  text?: string
}

// 流式中的 AI 消息块：segments 按事件到达顺序追加，天然穿插
export interface AiBlock {
  segments: AiSegment[]
  streaming: boolean
}
