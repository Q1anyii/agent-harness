import { useEffect, useRef } from 'react'
import type { AiBlock, AiSegment, ChatMessage } from '../types'
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
  segments: AiSegment[]
}

// 扁平消息 → 块状消息盒子（②⑥ 穿插式）：
//   user                    → 右侧用户消息
//   assistant(tool_calls)   → AI 块：按时间序展开段——
//                             决策思考(reasoning) → 每个工具调用一个 tool 段 →（结果按 id 回填）
//                             → 总结思考(reasoning) → 最终回复文本段
//   tool                    → 归属其前的 assistant 决策块（不单独成消息）
export function buildRenderItems(messages: ChatMessage[]): RenderItem[] {
  const items: RenderItem[] = []
  let i = 0
  // key 用全局自增计数：AI 块会"消费"后续多条消息（tool/总结），若用消息索引做 key，
  // 与下一条 user 消息的索引会重复，React 列表渲染错乱（新消息区显示旧回复）
  let keySeq = 0
  while (i < messages.length) {
    const m = messages[i]
    if (m.role === 'user') {
      items.push({ key: keySeq++, role: 'user', content: m.content ?? '', segments: [] })
      i++
      continue
    }
    if (m.role === 'assistant' && m.tool_calls && m.tool_calls.length > 0) {
      // AI 块开始：决策思考在前（穿插第一段）
      const segments: AiSegment[] = []
      let segIdx = 0
      if (m.reasoning) {
        segments.push({ type: 'reasoning', key: `r${i}-${segIdx++}`, reasoning: m.reasoning })
      }
      // 每个工具调用一个独立 tool 段（arguments 是 JSON 字符串 → 对象）
      for (const tc of m.tool_calls) {
        let args: Record<string, unknown> = {}
        try {
          args = tc.arguments ? (JSON.parse(tc.arguments) as Record<string, unknown>) : {}
        } catch {
          args = { raw: tc.arguments }
        }
        segments.push({ type: 'tool', key: `t${i}-${tc.id}`, tool: { id: tc.id, name: tc.name, args } })
      }
      i++
      // 收集紧随其后的 tool 结果消息（按 tool_call_id 配对回填）
      while (i < messages.length && messages[i].role === 'tool') {
        const tm = messages[i]
        for (const seg of segments) {
          if (seg.type === 'tool' && seg.tool && seg.tool.id === tm.tool_call_id) {
            seg.tool.result = tm.content ?? ''
            seg.tool.status = (tm.content ?? '').startsWith('错误') ? 'error' : 'success'
          }
        }
        i++
      }
      // 该块最终的 assistant 总结消息（可带思考 + 文本）→ 继续穿插
      let content = ''
      if (i < messages.length && messages[i].role === 'assistant' && !messages[i].tool_calls) {
        const sm = messages[i]
        if (sm.reasoning) {
          segments.push({ type: 'reasoning', key: `r${i}-${segIdx++}`, reasoning: sm.reasoning })
        }
        content = sm.content ?? ''
        if (content) {
          segments.push({ type: 'text', key: `x${i}-${segIdx++}`, text: content })
        }
        i++
      }
      items.push({ key: keySeq++, role: 'assistant', content, segments })
      continue
    }
    if (m.role === 'assistant') {
      // 纯文本 AI 消息：思考段（如有）+ 文本段
      const segments: AiSegment[] = []
      if (m.reasoning) segments.push({ type: 'reasoning', key: `r${i}`, reasoning: m.reasoning })
      if (m.content) segments.push({ type: 'text', key: `x${i}`, text: m.content })
      items.push({ key: keySeq++, role: 'assistant', content: m.content ?? '', segments })
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
  const scrollRef = useRef<HTMLDivElement | null>(null)

  // 消息窗口自动滚动：新消息/流式内容到达时滑动到底部（用户可手动回看历史）
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, streaming])

  return (
    <div className="chat-box">
      <div className="chat-header">Agent 对话</div>
      <div className="chat-messages" ref={scrollRef}>
        {items.map((item) =>
          item.role === 'user' ? (
            <div key={item.key} className="msg msg-user">
              <span className="msg-content">{item.content}</span>
              <span className="msg-label">用户</span>
            </div>
          ) : (
            <AiMessageBox key={item.key} segments={item.segments} />
          ),
        )}
        {streaming && <AiMessageBox key="streaming" segments={streaming.segments} streaming />}
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
