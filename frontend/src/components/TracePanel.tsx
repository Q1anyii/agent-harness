import type { TraceItem } from '../types'

// 工具 trace 以 div 形式呈现：每个工具调用渲染为一个 trace-item div
interface Props {
  trace: TraceItem[]
}

export default function TracePanel({ trace }: Props) {
  if (trace.length === 0) {
    return <div className="trace-panel">暂无工具调用记录</div>
  }
  return (
    <div className="trace-panel">
      <div className="trace-header">工具调用 Trace（共 {trace.length} 条）</div>
      {trace.map((item, i) => (
        <div key={i} className={`trace-item trace-${item.status}`}>
          <div className="trace-head">
            <span className="trace-tool">{item.tool}</span>
            <span className={`trace-status trace-status-${item.status}`}>{item.status}</span>
            <span className="trace-duration">{item.duration_ms} ms</span>
          </div>
          <div className="trace-args">参数：{JSON.stringify(item.args)}</div>
          <div className="trace-result">结果：{item.result}</div>
        </div>
      ))}
    </div>
  )
}
