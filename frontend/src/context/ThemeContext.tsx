import { useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react"
import { theme } from "antd"
import {
  SKINS,
  ThemeContext,
  withAlpha,
  type BackgroundSetting,
  type ThemeMode,
  type ThemeState,
} from "./theme-context"

const STORAGE_KEY = "drill-system:theme"

interface PersistedTheme {
  mode: ThemeMode
  skinId: string
  bg: BackgroundSetting | null
}

function loadPersisted(): PersistedTheme {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { mode: "light", skinId: SKINS[0].id, bg: null }
    const parsed = JSON.parse(raw) as Partial<PersistedTheme>
    return {
      mode: parsed.mode === "dark" ? "dark" : "light",
      skinId: SKINS.some((s) => s.id === parsed.skinId) ? (parsed.skinId as string) : SKINS[0].id,
      bg:
        parsed.bg &&
        typeof parsed.bg.image === "string" &&
        parsed.bg.image.length > 0 &&
        (parsed.bg.kind === "photo" || parsed.bg.kind === "gradient")
          ? { kind: parsed.bg.kind, image: parsed.bg.image, opacity: clamp(parsed.bg.opacity, 0.3, 1), blur: clamp(parsed.bg.blur, 0, 20) }
          : null,
    }
  } catch {
    return { mode: "light", skinId: SKINS[0].id, bg: null }
  }
}

function clamp(v: number, lo: number, hi: number): number {
  const n = Number(v)
  if (!Number.isFinite(n)) return lo
  return Math.max(lo, Math.min(hi, n))
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [persisted, setPersisted] = useState<PersistedTheme>(loadPersisted)

  const skin = useMemo(
    () => SKINS.find((s) => s.id === persisted.skinId) ?? SKINS[0],
    [persisted.skinId],
  )

  const themeConfig = useMemo<ThemeState["themeConfig"]>(() => {
    const token: Record<string, string | number> = {
      colorPrimary: skin.colorPrimary,
      borderRadius: skin.borderRadius,
    }
    // 有背景时面板变透：colorBgContainer 按「面板不透明度」换算成 rgba，
    // 弹层（colorBgElevated）保持接近实底，保证下拉/弹窗可读。
    if (persisted.bg) {
      token.colorBgContainer = withAlpha(persisted.mode === "dark" ? "#1f1f1f" : "#ffffff", persisted.bg.opacity)
      token.colorBgElevated = withAlpha(persisted.mode === "dark" ? "#1f1f1f" : "#ffffff", Math.max(persisted.bg.opacity, 0.94))
    }
    return {
      algorithm: persisted.mode === "dark" ? theme.darkAlgorithm : theme.defaultAlgorithm,
      token,
    }
  }, [persisted.mode, persisted.skinId, persisted.bg, skin])

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted))
    } catch {
      // 忽略存储失败（隐私模式等场景）
    }
  }, [persisted])

  // 同步 <body> 底色与文字色，避免滚动/过扫时露出与主题不符的底色
  useEffect(() => {
    const dark = persisted.mode === "dark"
    document.body.style.background = dark ? "#000000" : "#f5f5f5"
    document.body.style.color = dark ? "rgba(255, 255, 255, 0.88)" : "#1f2329"
  }, [persisted.mode])

  const setMode = useCallback((mode: ThemeMode) => setPersisted((s) => ({ ...s, mode })), [])
  const setSkin = useCallback((skinId: string) => setPersisted((s) => ({ ...s, skinId })), [])
  const setBg = useCallback(
    (bg: BackgroundSetting) => setPersisted((s) => ({ ...s, bg })),
    [],
  )
  const clearBg = useCallback(() => setPersisted((s) => ({ ...s, bg: null })), [])

  const value = useMemo<ThemeState>(
    () => ({
      mode: persisted.mode,
      skinId: persisted.skinId,
      skin,
      skins: SKINS,
      bg: persisted.bg,
      themeConfig,
      setMode,
      setSkin,
      setBg,
      clearBg,
    }),
    [persisted.mode, persisted.skinId, persisted.bg, skin, themeConfig, setMode, setSkin, setBg, clearBg],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error("useTheme 必须在 ThemeProvider 内使用")
  return ctx
}
