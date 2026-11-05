import { useEffect, useRef, useState } from 'react'
import type { AiBlock } from '../types'
import ToolCallCard from './ToolCallCard'

interface Props {
  block: AiBlock
}

// ⑥+② AI 消息块：思考过程（折叠）+ 工具调用子组件（循环）+ 最终回复（流式打字机）
export default function AiMessageBox({ block }: Props) {
  const [shown, setShown] = useState(0)
  const rafRef = useRef<number | null>(null)

  // 流式打字机：streaming 期间按帧推进已显示字符数（纯前端效果；
  // 真实逐 token 流后续由后端 stream 接口 + message_delta 驱动）
  useEffect(() => {
    if (!block.streaming) return
    const step = () => {
      setShown((prev) => {
        if (prev >= block.content.length) {
          if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
          return prev
        }
        const next = Math.min(prev + 6, block.content.length)
        rafRef.current = requestAnimationFrame(step)
        return next
      })
    }
    rafRef.current = requestAnimationFrame(step)
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    }
  }, [block.content, block.streaming])

  // 非流式（历史消息）：一次性显示全部
  const visible = block.streaming ? block.content.slice(0, shown) : block.content

  return (
    <div className="msg msg-assistant">
      <span className="msg-label">Agent</span>
      <div className="msg-body">
        {block.reasoning && (
          <details className="reasoning-box">
            <summary>思考过程</summary>
            <div className="reasoning-content">{block.reasoning}</div>
          </details>
        )}
        {block.toolCalls.length > 0 && (
          <div className="tool-card-list">
            {block.toolCalls.map((call) => (
              <ToolCallCard key={call.id} call={call} />
            ))}
          </div>
        )}
        {visible && <div className="msg-content ai-content">{visible}</div>}
        {block.streaming && !visible && <div className="ai-thinking">思考中…</div>}
      </div>
    </div>
  )
}
