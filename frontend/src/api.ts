// 后端 API 封装：所有请求走相对路径 /api，dev 模式下由 Vite proxy 转发到 FastAPI
import type { ChatMessage, ChatResult, SessionInfo, TraceItem } from './types'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: string } | null
    throw new Error(body?.detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  createSession: () => request<SessionInfo>('/api/sessions', { method: 'POST' }),

  listSessions: () => request<{ sessions: SessionInfo[] }>('/api/sessions'),

  getMessages: (sid: string) =>
    request<{ messages: ChatMessage[] }>(`/api/sessions/${sid}/messages`),

  sendMessage: (sid: string, content: string) =>
    request<ChatResult>(`/api/sessions/${sid}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    }),

  getTrace: (sid: string) =>
    request<{ trace: TraceItem[] }>(`/api/sessions/${sid}/trace`),
}
