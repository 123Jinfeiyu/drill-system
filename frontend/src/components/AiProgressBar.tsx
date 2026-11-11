import { useEffect, useState } from "react"
import { Progress, Typography } from "antd"

interface AiProgressBarProps {
  active: boolean
  label?: string
  tip?: string
}

/**
 * AI 生成进度条（本地模型无服务端流式进度，这里用“先快后慢逼近 92%”的动画反馈等待时长，
 * 响应返回后由父组件把 active 置 false 即可复位）。
 */
export default function AiProgressBar({
  active,
  label = "AI 正在回复",
  tip = "本地模型较慢，约 40–70 秒",
}: AiProgressBarProps) {
  const [percent, setPercent] = useState(0)
  const [secs, setSecs] = useState(0)

  useEffect(() => {
    if (!active) {
      setPercent(0)
      setSecs(0)
      return
    }
    setPercent(4)
    setSecs(0)
    const start = Date.now()
    const id = window.setInterval(() => {
      const elapsed = (Date.now() - start) / 1000
      setSecs(Math.floor(elapsed))
      // 前 8 秒快速涨到 45%，之后缓慢逼近 92%
      const p =
        elapsed < 8
          ? 4 + (elapsed / 8) * 41
          : 45 + Math.min(47, (elapsed - 8) * 1.2)
      setPercent(Math.min(92, p))
    }, 250)
    return () => window.clearInterval(id)
  }, [active])

  if (!active) return null

  return (
    <div style={{ padding: "2px 0" }}>
      <Progress
        percent={Math.round(percent)}
        status="active"
        size="small"
        strokeColor={{ from: "#108ee9", to: "#87d068" }}
      />
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {label} · 已等待 {secs} 秒{tip ? `（${tip}）` : ""}
      </Typography.Text>
    </div>
  )
}
