import { useState } from "react"
import { App as AntdApp, Button, Drawer, Slider, Space, Typography, Upload } from "antd"
import { DeleteOutlined, UploadOutlined } from "@ant-design/icons"
import { useTheme } from "../context/ThemeContext"
import { GRADIENT_PRESETS, withAlpha, type BackgroundSetting } from "../context/theme-context"
import { fileToDataUrl } from "../utils/background"

/**
 * 背景设置抽屉：上传照片 / 内置渐变 / 面板不透明度 / 背景模糊。
 * 滑杆直接改当前设置并即时持久化（Provider 里同步写 localStorage）。
 */
export default function BackgroundSettings({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { bg, setBg, clearBg, mode } = useTheme()
  const { message } = AntdApp.useApp()
  const [busy, setBusy] = useState(false)

  const applyPhoto = async (file: File) => {
    setBusy(true)
    try {
      const dataUrl = await fileToDataUrl(file)
      setBg({ kind: "photo", image: dataUrl, opacity: bg?.opacity ?? 0.88, blur: bg?.blur ?? 0 })
      message.success("背景已更新")
    } catch {
      message.error("这张图读不出来，换一张试试")
    } finally {
      setBusy(false)
    }
    // 阻止 Upload 默认上传行为
    return false
  }

  const patch = (partial: Partial<BackgroundSetting>) => {
    if (!bg) return
    setBg({ ...bg, ...partial })
  }

  return (
    <Drawer
      title="背景与外观"
      placement="right"
      width={380}
      open={open}
      onClose={onClose}
      footer={
        <Space style={{ justifyContent: "space-between", width: "100%" }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            设置保存在本机浏览器，换设备不跟随
          </Typography.Text>
          <Button danger icon={<DeleteOutlined />} disabled={!bg} onClick={() => { clearBg(); message.success("已恢复默认背景") }}>
            恢复默认
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size={20} style={{ width: "100%" }}>
        <div>
          <Typography.Text strong>照片背景</Typography.Text>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
            图片只存在你自己的浏览器里，不会上传服务器；过大的图会自动压缩
          </Typography.Paragraph>
          <Upload.Dragger
            accept="image/*"
            showUploadList={false}
            beforeUpload={(file) => {
              void applyPhoto(file as File)
              return false
            }}
            disabled={busy}
          >
            <Button icon={<UploadOutlined />} loading={busy}>
              选择图片
            </Button>
            <div style={{ marginTop: 8, color: "#999", fontSize: 12 }}>点击或拖入图片（JPG / PNG / WebP）</div>
          </Upload.Dragger>
        </div>

        <div>
          <Typography.Text strong>内置渐变</Typography.Text>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginTop: 8 }}>
            {GRADIENT_PRESETS.map((g) => {
              const active = bg?.kind === "gradient" && bg.image === g.image
              return (
                <button
                  key={g.id}
                  type="button"
                  onClick={() => setBg({ kind: "gradient", image: g.image, opacity: bg?.opacity ?? 0.88, blur: bg?.blur ?? 0 })}
                  style={{
                    height: 56,
                    borderRadius: 8,
                    cursor: "pointer",
                    background: g.image,
                    border: active ? "2px solid #1677ff" : "1px solid rgba(0,0,0,0.12)",
                    color: "#fff",
                    textShadow: "0 1px 2px rgba(0,0,0,0.5)",
                    fontSize: 12,
                  }}
                >
                  {g.name}
                </button>
              )
            })}
          </div>
        </div>

        <div>
          <Space style={{ justifyContent: "space-between", width: "100%" }}>
            <Typography.Text strong>面板不透明度</Typography.Text>
            <Typography.Text type="secondary">{bg ? Math.round(bg.opacity * 100) : 100}%</Typography.Text>
          </Space>
          <Slider
            min={30}
            max={100}
            value={bg ? Math.round(bg.opacity * 100) : 100}
            disabled={!bg}
            onChange={(v) => patch({ opacity: v / 100 })}
            tooltip={{ formatter: (v) => `${v}%` }}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            越小面板越透，背景越明显；建议 80% 以上保证文字可读
          </Typography.Text>
        </div>

        <div>
          <Space style={{ justifyContent: "space-between", width: "100%" }}>
            <Typography.Text strong>背景模糊</Typography.Text>
            <Typography.Text type="secondary">{bg?.blur ?? 0}px</Typography.Text>
          </Space>
          <Slider min={0} max={20} value={bg?.blur ?? 0} disabled={!bg} onChange={(v) => patch({ blur: v })} />
        </div>

        <div style={{ borderTop: "1px dashed rgba(128,128,128,0.35)", paddingTop: 12 }}>
          <Typography.Text strong>当前主题色</Typography.Text>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: "4px 0 0" }}>
            主题色与亮暗模式仍在顶部「皮肤」按钮里切换，与背景叠加生效。
          </Typography.Paragraph>
          <div
            style={{
              marginTop: 8,
              height: 40,
              borderRadius: 8,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: withAlpha(mode === "dark" ? "#1f1f1f" : "#ffffff", bg?.opacity ?? 1),
              border: "1px solid rgba(128,128,128,0.3)",
            }}
          >
            <span style={{ color: mode === "dark" ? "rgba(255,255,255,0.88)" : "rgba(0,0,0,0.88)" }}>
              面板效果预览
            </span>
          </div>
        </div>
      </Space>
    </Drawer>
  )
}
