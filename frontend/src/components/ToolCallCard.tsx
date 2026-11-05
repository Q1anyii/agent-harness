import type { ToolCallBlock } from '../types'

// ② 工具调用子组件：AI 消息块内的一个工具卡片（名称/参数/结果/耗时/状态）
export default function ToolCallCard({ call }: { call: ToolCallBlock }) {
  return (
    <div className={`tool-card ${call.status === 'error' ? 'tool-card-error' : ''}`}>
      <div className="tool-card-head">
        <span className="tool-card-name">🔧 {call.name}</span>
        {call.duration_ms !== undefined && (
          <span className="tool-card-duration">{call.duration_ms} ms</span>
        )}
        {call.status && (
          <span className={`tool-card-status tool-card-status-${call.status}`}>
            {call.status === 'success' ? '成功' : call.status}
          </span>
        )}
      </div>
      <div className="tool-card-body">
        <div className="tool-card-args">参数：{JSON.stringify(call.args)}</div>
        {call.result !== undefined && (
          <div className="tool-card-result">结果：{call.result}</div>
        )}
      </div>
    </div>
  )
}
