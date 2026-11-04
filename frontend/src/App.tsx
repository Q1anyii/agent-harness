import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
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
    try {
      setCurrentId(sid)
      setError(null)
      const [msgs, tr] = await Promise.all([api.getMessages(sid), api.getTrace(sid)])
      setMessages(msgs.messages)
      setTrace(tr.trace)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const deleteSession = async (sid: string) => {
    try {
      await api.deleteSession(sid)
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
      setMessages((prev) => [...prev, { role: 'assistant', content: result.reply }])
      setTrace((prev) => [...prev, ...result.trace])
      void refreshSessions()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
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
