import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { storage } from './storage'
import type { AiBlock, ChatMessage, SessionInfo, StreamEvent, TraceItem } from './types'
import SessionList from './components/SessionList'
import ChatBox from './components/ChatBox'
import TracePanel from './components/TracePanel'

export default function App() {
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [trace, setTrace] = useState<TraceItem[]>([])
  const [streaming, setStreaming] = useState<AiBlock | null>(null)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 流式轮询句柄与续拉锚点（④）：1s 级 setInterval，增量消费事件
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const seqRef = useRef(0)

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

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
    return () => stopPolling()
  }, [refreshSessions, stopPolling])

  // 自动选中：当前无会话时，自动选中列表第一个（配合后端惰性建会话，打开即用）
  useEffect(() => {
    if (!currentId && sessions.length > 0) {
      void selectSession(sessions[0].session_id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions, currentId])

  const createSession = async () => {
    stopPolling()
    try {
      const s = await api.createSession()
      setCurrentId(s.session_id)
      setMessages([])
      setTrace([])
      setStreaming(null)
      setError(null)
      void refreshSessions()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const selectSession = async (sid: string) => {
    stopPolling()
    setStreaming(null)
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
        stopPolling()
        setCurrentId(null)
        setMessages([])
        setTrace([])
        setStreaming(null)
      }
      setError(null)
      void refreshSessions()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  // 增量事件 → 组装进当前 AI 消息块（⑥ reasoning + ② 工具子组件 + 回复增量）
  const applyEvents = useCallback((events: StreamEvent[]) => {
    setStreaming((prev) => {
      if (!prev) return prev
      const next: AiBlock = { ...prev, toolCalls: [...prev.toolCalls] }
      for (const ev of events) {
        if (ev.type === 'reasoning') {
          next.reasoning += ev.content ?? ''
        } else if (ev.type === 'tool_call') {
          next.toolCalls.push({ id: ev.id ?? '', name: ev.name ?? '', args: ev.args ?? {} })
        } else if (ev.type === 'tool_result') {
          const target = next.toolCalls.find((tc) => tc.id === ev.id)
          if (target) {
            target.result = ev.result
            target.status = ev.status
            target.duration_ms = ev.duration_ms
          }
        } else if (ev.type === 'message_delta') {
          next.content += ev.delta ?? ''
        }
      }
      return next
    })
  }, [])

  // 启动 1s 级轮询：增量拉取事件；轮询失败静默（下轮重试），断连恢复靠全量刷新兜底
  const startPolling = useCallback(
    (sid: string) => {
      stopPolling()
      pollRef.current = setInterval(async () => {
        try {
          const res = await api.getEvents(sid, seqRef.current)
          if (res.events.length > 0) applyEvents(res.events)
          seqRef.current = res.latest_seq
        } catch {
          /* 轮询失败忽略：下个 tick 重试；生成完成后 POST 返回会停止轮询 */
        }
      }, 1000)
    },
    [applyEvents, stopPolling],
  )

  const send = async () => {
    const content = input.trim()
    if (!content || !currentId || busy) return
    setBusy(true)
    setError(null)
    setMessages((prev) => [...prev, { role: 'user', content }])
    setInput('')
    // 流式：先挂起空 AI 块（思考中），同时启动事件轮询
    setStreaming({ reasoning: '', toolCalls: [], content: '', streaming: true })
    seqRef.current = 0
    startPolling(currentId)
    try {
      await api.sendMessage(currentId, content)
      // 生成完成：以服务端消息为准刷新全量（消息/工具调用已由 runtime 写回 session）
      const msgs = await api.getMessages(currentId)
      setMessages(msgs.messages)
      storage.saveMessages(currentId, msgs.messages)
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
      stopPolling()
      setStreaming(null)
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
            streaming={streaming}
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
