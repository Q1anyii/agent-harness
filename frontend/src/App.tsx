import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { storage } from './storage'
import type { ChatMessage, SessionInfo, TraceItem } from './types'
import SessionList from './components/SessionList'
import ChatBox from './components/ChatBox'
import TracePanel from './components/TracePanel'

export default function App() {
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [trace, setTrace] = useState<TraceItem[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refreshSessions = useCallback(async () => {
    try {
      const res = await api.listSessions()
      setSessions(res.sessions)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    void refreshSessions()
  }, [refreshSessions])

  // 自动选中：当前无会话时，自动选中列表第一个（配合后端惰性建会话，打开即用）
  useEffect(() => {
    if (!currentId && sessions.length > 0) {
      void selectSession(sessions[0].session_id)
    }
  }, [sessions, currentId])

  const createSession = async () => {
    try {
      const s = await api.createSession()
      setCurrentId(s.session_id)
      setMessages([])
      setTrace([])
      setError(null)
      void refreshSessions()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const selectSession = async (sid: string) => {
    setCurrentId(sid)
    setError(null)
    // 先渲染本地缓存（后端重启/刷新页面时历史不丢），再以后端为准刷新
    const cachedMsgs = storage.loadMessages(sid)
    const cachedTr = storage.loadTrace(sid)
    if (cachedMsgs) setMessages(cachedMsgs)
    if (cachedTr) setTrace(cachedTr)
    try {
      const [msgs, tr] = await Promise.all([api.getMessages(sid), api.getTrace(sid)])
      setMessages(msgs.messages)
      setTrace(tr.trace)
      storage.saveMessages(sid, msgs.messages)
      storage.saveTrace(sid, tr.trace)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      if (msg.includes('404') || msg.includes('会话不存在')) {
        // 后端已无此会话（如服务重启）：保留本地缓存展示，发送时自动新建
        setError('该会话在后端已失效，当前展示本地缓存历史；发送消息将自动新建会话')
      } else {
        setError(msg)
      }
    }
  }

  const deleteSession = async (sid: string) => {
    try {
      await api.deleteSession(sid)
      storage.removeMessages(sid)
      storage.removeTrace(sid)
      if (currentId === sid) {
        setCurrentId(null)
        setMessages([])
        setTrace([])
      }
      setError(null)
      void refreshSessions()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const send = async () => {
    const content = input.trim()
    if (!content || !currentId || busy) return
    setBusy(true)
    setError(null)
    setMessages((prev) => [...prev, { role: 'user', content }])
    setInput('')
    try {
      const result = await api.sendMessage(currentId, content)
      setMessages((prev) => {
        const next: ChatMessage[] = [...prev, { role: 'assistant', content: result.reply }]
        storage.saveMessages(currentId, next)
        return next
      })
      setTrace((prev) => {
        const next = [...prev, ...result.trace]
        storage.saveTrace(currentId, next)
        return next
      })
      void refreshSessions()
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      if (msg.includes('404') || msg.includes('会话不存在')) {
        // 后端已无此会话（如服务重启）：自动新建会话，避免旧 id 持续失效
        const s = await api.createSession()
        setCurrentId(s.session_id)
        setMessages([])
        setTrace([])
        setError('原会话已失效，已自动新建会话')
        void refreshSessions()
      } else {
        setError(msg)
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <SessionList
          sessions={sessions}
          currentId={currentId}
          onCreate={createSession}
          onSelect={selectSession}
          onDelete={deleteSession}
        />
      </aside>
      <main className="main">
        <div className="main-row">
          <ChatBox
            messages={messages}
            input={input}
            busy={busy}
            onInput={setInput}
            onSend={send}
            disabled={!currentId}
          />
          <TracePanel trace={trace} />
        </div>
        {error && <div className="error-bar">{error}</div>}
      </main>
    </div>
  )
}
