// 前端本地缓存：后端当前为内存存储、重启即丢，用 localStorage 兜底保存消息历史
// key 按会话隔离：agent-harness:msg:{sid} / agent-harness:trace:{sid}
import type { ChatMessage, TraceItem } from './types'

const MSG_PREFIX = 'agent-harness:msg:'
const TRACE_PREFIX = 'agent-harness:trace:'

function load<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    // 解析失败/隐私模式等场景视为无缓存
    return null
  }
}

function save(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // 配额超限等场景静默失败，不影响主流程
  }
}

function remove(key: string): void {
  localStorage.removeItem(key)
}

export const storage = {
  loadMessages: (sid: string): ChatMessage[] | null => load<ChatMessage[]>(MSG_PREFIX + sid),
  saveMessages: (sid: string, msgs: ChatMessage[]): void => save(MSG_PREFIX + sid, msgs),
  removeMessages: (sid: string): void => remove(MSG_PREFIX + sid),

  loadTrace: (sid: string): TraceItem[] | null => load<TraceItem[]>(TRACE_PREFIX + sid),
  saveTrace: (sid: string, tr: TraceItem[]): void => save(TRACE_PREFIX + sid, tr),
  removeTrace: (sid: string): void => remove(TRACE_PREFIX + sid),
}
