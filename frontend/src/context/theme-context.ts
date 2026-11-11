import { createContext } from "react"
import type { ThemeConfig } from "antd"

export type ThemeMode = "light" | "dark"

export interface SkinPreset {
  id: string
  name: string
  colorPrimary: string
  borderRadius: number
}

/** 照片/渐变背景。``image``：photo 存 dataURL，gradient 存 CSS background 值 */
export interface BackgroundSetting {
  kind: "photo" | "gradient"
  image: string
  /** 面板不透明度 0.3–1（越小越透） */
  opacity: number
  /** 背景模糊 px 0–20 */
  blur: number
}

export const GRADIENT_PRESETS: { id: string; name: string; image: string }[] = [
  { id: "aurora", name: "极光", image: "linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%)" },
  { id: "sunset", name: "暮色", image: "linear-gradient(135deg, #355c7d 0%, #6c5b7b 55%, #c06c84 100%)" },
  { id: "mint", name: "薄荷", image: "linear-gradient(135deg, #d4fc79 0%, #96e6a1 100%)" },
  { id: "ink", name: "水墨", image: "linear-gradient(160deg, #e0eafc 0%, #cfdef3 60%, #a6c1ee 100%)" },
]

/** hex/rgb 颜色加透明度（token.colorBgContainer 通常是 hex） */
export function withAlpha(color: string, alpha: number): string {
  const a = Math.max(0, Math.min(1, alpha))
  const m = color.trim()
  if (/^#[0-9a-f]{6}$/i.test(m)) {
    const r = parseInt(m.slice(1, 3), 16)
    const g = parseInt(m.slice(3, 5), 16)
    const b = parseInt(m.slice(5, 7), 16)
    return `rgba(${r}, ${g}, ${b}, ${a})`
  }
  const rgb = m.match(/^rgba?\(([^)]+)\)$/i)
  if (rgb) {
    const parts = rgb[1].split(",").map((s) => s.trim())
    return `rgba(${parts[0]}, ${parts[1]}, ${parts[2]}, ${a})`
  }
  return m
}

export const SKINS: SkinPreset[] = [
  { id: "blue", name: "海盐蓝", colorPrimary: "#1677ff", borderRadius: 6 },
  { id: "purple", name: "星云紫", colorPrimary: "#722ed1", borderRadius: 8 },
  { id: "teal", name: "薄荷青", colorPrimary: "#13c2c2", borderRadius: 8 },
  { id: "green", name: "森林绿", colorPrimary: "#52c41a", borderRadius: 6 },
  { id: "orange", name: "余烬橙", colorPrimary: "#fa8c16", borderRadius: 6 },
  { id: "rose", name: "蔷薇粉", colorPrimary: "#eb2f96", borderRadius: 10 },
]

export interface ThemeState {
  mode: ThemeMode
  skinId: string
  skin: SkinPreset
  skins: SkinPreset[]
  bg: BackgroundSetting | null
  themeConfig: ThemeConfig
  setMode: (mode: ThemeMode) => void
  setSkin: (skinId: string) => void
  setBg: (bg: BackgroundSetting) => void
  clearBg: () => void
}

// createContext 实例独立存放，避免 react-refresh boundary 重新求值导致实例不一致
export const ThemeContext = createContext<ThemeState | undefined>(undefined)
