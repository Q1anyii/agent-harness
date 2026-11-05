import type { AiBlock, ChatMessage, ToolCallBlock } from '../types'
import AiMessageBox from './AiMessageBox'

interface Props {
  messages: ChatMessage[]
  streaming: AiBlock | null
  input: string
  busy: boolean
  disabled: boolean
  onInput: (v: string) => void
  onSend: () => void
}

export interface RenderItem {
  key: number
  role: 'user' | 'assistant'
  content: string
  toolCalls: ToolCallBlock[]
}

// 扁平消息 → 块状消息盒子（②）：
//   user                  → 右侧用户消息
//   assistant(tool_calls) → AI 块：工具调用子组件列表（与后续 tool 结果按 id 配对）+ 最终回复文本
//   tool                  → 归属其前的 assistant 决策块（不单独成消息）
export function buildRenderItems(messages: ChatMessage[]): RenderItem[] {
  const items: RenderItem[] = []
  let i = 0
  while (i < messages.length) {
    const m = messages[i]
    if (m.role === 'user') {
      items.push({ key: i, role: 'user', content: m.content ?? '', toolCalls: [] })
      i++
      continue
    }
    if (m.role === 'assistant' && m.tool_calls && m.tool_calls.length > 0) {
      // AI 块开始：解析工具调用（arguments 是 JSON 字符串 → 对象）
      const toolCalls: ToolCallBlock[] = m.tool_calls.map((tc) => {
        let args: Record<string, unknown> = {}
        try {
          args = tc.arguments ? (JSON.parse(tc.arguments) as Record<string, unknown>) : {}
        } catch {
          args = { raw: tc.arguments }
        }
        return { id: tc.id, name: tc.name, args }
      })
      i++
      // 收集紧随其后的 tool 结果消息（按 tool_call_id 配对回填）
      while (i < messages.length && messages[i].role === 'tool') {
        const tm = messages[i]
        const target = toolCalls.find((tc) => tc.id === tm.tool_call_id)
        if (target) {
          target.result = tm.content ?? ''
          target.status = (tm.content ?? '').startsWith('错误') ? 'error' : 'success'
        }
        i++
      }
      // 该块最终的 assistant 总结文本（如有）
      let content = ''
      if (i < messages.length && messages[i].role === 'assistant' && !messages[i].tool_calls) {
        content = messages[i].content ?? ''
        i++
      }
      items.push({ key: i, role: 'assistant', content, toolCalls })
      continue
    }
    if (m.role === 'assistant') {
      items.push({ key: i, role: 'assistant', content: m.content ?? '', toolCalls: [] })
      i++
      continue
    }
    // 孤立 tool 消息（协议上不应出现）：跳过
    i++
  }
  return items
}

export default function ChatBox({ messages, streaming, input, busy, disabled, onInput, onSend }: Props) {
  const items = buildRenderItems(messages)
  return (
    <div className="chat-box">
      <div className="chat-header">Agent 对话</div>
      <div className="chat-messages">
        {items.map((item) =>
          item.role === 'user' ? (
            <div key={item.key} className="msg msg-user">
              <span className="msg-content">{item.content}</span>
              <span className="msg-label">用户</span>
            </div>
          ) : (
            <AiMessageBox
              key={item.key}
              block={{
                reasoning: '',
                toolCalls: item.toolCalls,
                content: item.content,
                streaming: false,
              }}
            />
          ),
        )}
        {streaming && <AiMessageBox block={streaming} />}
        {items.length === 0 && !streaming && <div className="chat-empty">输入消息，开始对话吧。</div>}
      </div>
      <div className="chat-input-row">
        <input
          className="chat-input"
          value={input}
          disabled={disabled || busy}
          placeholder={disabled ? '加载会话中…' : busy ? 'Agent 处理中…' : '输入消息，回车发送'}
          onChange={(e) => onInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onSend()
          }}
        />
        <button className="send-btn" disabled={disabled || busy} onClick={onSend}>
          {busy ? '处理中' : '发送'}
        </button>
      </div>
    </div>
  )
}
