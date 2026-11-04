import type { SessionInfo } from '../types'

interface Props {
  sessions: SessionInfo[]
  currentId: string | null
  onCreate: () => void
  onSelect: (sid: string) => void
  onDelete: (sid: string) => void
}

export default function SessionList({ sessions, currentId, onCreate, onSelect, onDelete }: Props) {
  return (
    <div className="session-list">
      <button className="new-session" onClick={onCreate}>
        + 新建会话
      </button>
      <ul>
        {sessions.map((s) => (
          <li key={s.session_id} className="session-row">
            <button
              className={s.session_id === currentId ? 'session-item active' : 'session-item'}
              onClick={() => onSelect(s.session_id)}
            >
              <span className="session-title">
                {s.message_count > 0 ? `会话 ${s.session_id.slice(0, 6)}` : '（空会话）'}
              </span>
              <span className="session-meta">
                {s.state} · {s.message_count} 条
              </span>
            </button>
            <button
              className="session-del"
              title="删除会话"
              onClick={(e) => {
                e.stopPropagation()
                onDelete(s.session_id)
              }}
            >
              ×
            </button>
          </li>
        ))}
        {sessions.length === 0 && <li className="session-empty">暂无会话</li>}
      </ul>
    </div>
  )
}
