/**
 * 上传图片 → 压缩成能塞进 localStorage 的 dataURL。
 * 背景图不走后端：它纯粹是个人外观偏好，落库没有意义。
 */
export async function fileToDataUrl(file: File, maxEdge = 1920, quality = 0.82): Promise<string> {
  const bitmap = await createImageBitmap(file)
  try {
    const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height))
    const w = Math.max(1, Math.round(bitmap.width * scale))
    const h = Math.max(1, Math.round(bitmap.height * scale))
    const canvas = document.createElement("canvas")
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext("2d")
    if (!ctx) throw new Error("画布不可用")
    ctx.drawImage(bitmap, 0, 0, w, h)
    let url = canvas.toDataURL("image/jpeg", quality)
    // localStorage 一般 5MB，给其余设置留余量
    if (url.length > 3_600_000) url = canvas.toDataURL("image/jpeg", 0.55)
    return url
  } finally {
    bitmap.close()
  }
}
