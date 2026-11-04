import type { ChatMessage } from '../types'

interface Props {
  messages: ChatMessage[]
  input: string
  busy: boolean
  disabled: boolean
  onInput: (v: string) => void
  onSend: () => void
}

export default function ChatBox({ messages, input, busy, disabled, onInput, onSend }: Props) {
  return (
    <div className="chat-box">
      <div className="chat-header">Agent 对话</div>
      <div className="chat-messages">
        {messages.map((m, i) => (
          <div key={i} className={`msg msg-${m.role}`}>
            <span className="msg-label">{m.role === 'user' ? '用户' : m.role === 'tool' ? `工具${m.name ? `·${m.name}` : ''}` : 'Agent'}</span>
            <span className="msg-content">{m.content}</span>
          </div>
        ))}
        {messages.length === 0 && <div className="chat-empty">输入消息，开始对话吧。</div>}
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
