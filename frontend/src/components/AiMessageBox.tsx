import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { AiSegment } from '../types'
import ToolCallCard from './ToolCallCard'

interface Props {
  segments: AiSegment[]
  streaming?: boolean
}

// ⑥+② AI 消息块（穿插式）：按时间序渲染段列表——
//   思考段（可折叠）→ 工具段（ToolCallCard 子组件）→ … → 最终回复文本段
export default function AiMessageBox({ segments, streaming = false }: Props) {
  // 打字机只作用于"最后一个文本段"：流式期间每 50ms 推进 3 个字符
  const [shown, setShown] = useState(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const textSeg = [...segments].reverse().find((s) => s.type === 'text')
  const text = textSeg?.text ?? ''

  useEffect(() => {
    if (!streaming) {
      setShown(text.length)
      return
    }
    // 文本增长（新事件批次到达）时继续推进，直到追上 text.length
    timerRef.current = setInterval(() => {
      setShown((prev) => {
        if (prev >= text.length) {
          if (timerRef.current !== null) clearInterval(timerRef.current)
          return prev
        }
        return Math.min(prev + 3, text.length)
      })
    }, 50)
    return () => {
      if (timerRef.current !== null) clearInterval(timerRef.current)
    }
  }, [text, streaming])

  return (
    <div className="msg msg-assistant">
      <span className="msg-label">Agent</span>
      <div className="msg-body">
        {segments.map((seg) => {
          if (seg.type === 'reasoning') {
            return (
              <details key={seg.key} className="reasoning-box">
                <summary>思考过程</summary>
                <div className="reasoning-content">{seg.reasoning}</div>
              </details>
            )
          }
          if (seg.type === 'tool' && seg.tool) {
            return <ToolCallCard key={seg.key} call={seg.tool} />
          }
          if (seg.type === 'text') {
            const isLastText = seg.key === textSeg?.key
            const segText = seg.text ?? ''
            const visible = streaming && isLastText ? segText.slice(0, shown) : segText
            return visible ? (
              <div key={seg.key} className="msg-content ai-content">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{visible}</ReactMarkdown>
              </div>
            ) : null
          }
          return null
        })}
        {streaming && !text && <div className="ai-thinking">思考中…</div>}
      </div>
    </div>
  )
}
