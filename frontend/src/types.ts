// 与后端 OpenAPI 契约对应的前端类型定义

export interface SessionInfo {
  session_id: string
  created_at: string
  state: string
  message_count: number
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'tool'
  content: string
  name?: string
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
