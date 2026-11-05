// 后端 API 封装：所有请求走相对路径 /api，dev 模式下由 Vite proxy 转发到 FastAPI
import type { ChatMessage, ChatResult, EventsResponse, SessionInfo, TraceItem } from './types'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: string } | null
    throw new Error(body?.detail ?? `HTTP ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  createSession: () => request<SessionInfo>('/api/sessions', { method: 'POST' }),

  listSessions: () => request<{ sessions: SessionInfo[] }>('/api/sessions'),

  deleteSession: (sid: string) => request<void>(`/api/sessions/${sid}`, { method: 'DELETE' }),

  getMessages: (sid: string) =>
    request<{ messages: ChatMessage[] }>(`/api/sessions/${sid}/messages`),

  sendMessage: (sid: string, content: string) =>
    request<ChatResult>(`/api/sessions/${sid}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    }),

  getTrace: (sid: string) =>
    request<{ trace: TraceItem[] }>(`/api/sessions/${sid}/trace`),

  // 流式事件轮询（④）：since 为上次已消费的最大 seq，增量拉取
  getEvents: (sid: string, since: number) =>
    request<EventsResponse>(`/api/sessions/${sid}/events?since=${since}`),
}
