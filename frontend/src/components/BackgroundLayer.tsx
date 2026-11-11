import type { CSSProperties } from "react"
import { useTheme } from "../context/ThemeContext"

/**
 * 全站最底层背景：照片（cover）或内置渐变。
 * fixed + zIndex 0，内容层（MainLayout / 登录页）各自 zIndex 1 压在上面。
 * 模糊用 scale(1.06) 抵消边缘发虚，否则四周会露出一条实色边。
 */
export default function BackgroundLayer() {
  const { bg } = useTheme()
  if (!bg) return null

  const style: CSSProperties =
    bg.kind === "photo"
      ? {
          backgroundImage: `url(${bg.image})`,
          backgroundSize: "cover",
          backgroundPosition: "center",
        }
      : { background: bg.image }

  return (
    <div
      aria-hidden
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 0,
        pointerEvents: "none",
        filter: bg.blur > 0 ? `blur(${bg.blur}px)` : undefined,
        transform: bg.blur > 0 ? "scale(1.06)" : undefined,
        ...style,
      }}
    />
  )
}
