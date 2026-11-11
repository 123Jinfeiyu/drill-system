/**
 * 浏览器录音：把 MediaRecorder 这套有点啰嗦的东西收成一个「开始 → 停止拿 Blob」。
 *
 * 三个实战上会踩的点，都在这里处理掉：
 *
 * 1. **编解码格式因内核而异**。Chrome/Edge/Firefox 给 `audio/webm;codecs=opus`，
 *    Safari 给 `audio/mp4`。所以用 `isTypeSupported` 挨个试，而不是写死一个。
 * 2. **麦克风必须显式还回去**。`getUserMedia` 拿到的 stream 不 stop 掉，浏览器标签页上
 *    会一直亮着「正在录音」，接下一通电话时坐席会以为自己还在录。
 * 3. **权限失败要说人话**。`NotAllowedError` 直接抛给用户看等于没说，
 *    这里翻成「点地址栏那个锁，把麦克风权限放开」这类可操作的提示。
 */

export interface RecordingResult {
  blob: Blob
  durationMs: number
  mime: string
}

export interface RecordingSession {
  /** 实际使用的 MIME（带 codecs 参数），上传时用裸类型 */
  readonly mime: string
  /** 开始录制的时间戳（ms） */
  readonly startedAt: number
  /** 已录时长（ms），用于界面上的计时 */
  elapsed(): number
  /** 停止并拿到结果 */
  stop(): Promise<RecordingResult>
  /** 放弃这次录制（丢掉数据、还回麦克风） */
  cancel(): void
}

/** 按「兼容性从好到差」排，第一个被支持的就是要用的 */
const CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
]

export function recordingSupported(): boolean {
  return (
    typeof navigator !== "undefined" &&
    typeof window !== "undefined" &&
    typeof window.MediaRecorder !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia
  )
}

export function pickMimeType(): string {
  if (typeof window === "undefined" || typeof window.MediaRecorder === "undefined") return ""
  for (const candidate of CANDIDATES) {
    try {
      if (window.MediaRecorder.isTypeSupported(candidate)) return candidate
    } catch {
      // 某些内核在传奇怪字符串时会抛，继续试下一个
    }
  }
  return ""
}

function explainMicError(err: unknown): string {
  const name = (err as { name?: string } | null)?.name ?? ""
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return "麦克风权限被拒。点地址栏左边的锁图标，把「麦克风」改成允许后重试。"
    case "NotFoundError":
    case "DevicesNotFoundError":
      return "没检测到麦克风。插上耳机或确认设备已启用。"
    case "NotReadableError":
    case "TrackStartError":
      return "麦克风被别的程序占着（比如会议软件）。关掉它再试。"
    case "OverconstrainedError":
      return "当前麦克风不支持所需的录音参数，换一个输入设备试试。"
    default:
      return `打不开麦克风：${err instanceof Error ? err.message : String(err)}`
  }
}

export async function startRecording(): Promise<RecordingSession> {
  if (!recordingSupported()) {
    throw new Error(
      "当前浏览器不支持录音（或页面不是 HTTPS/localhost）。请用 Chrome / Edge，并通过 https 或 localhost 打开。",
    )
  }

  let stream: MediaStream
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    })
  } catch (err) {
    throw new Error(explainMicError(err))
  }

  const mime = pickMimeType()
  const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
  const chunks: Blob[] = []
  const startedAt = Date.now()
  let released = false

  const releaseMic = () => {
    if (released) return
    released = true
    stream.getTracks().forEach((track) => track.stop())
  }

  recorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) chunks.push(event.data)
  }
  // 出错也要把麦克风还回去，否则「录失败了但红灯一直亮」
  recorder.onerror = () => releaseMic()
  recorder.onstop = () => releaseMic()

  // 每 250ms 落一块：停止时不必等最后一大块，感知上快很多
  recorder.start(250)

  const session: RecordingSession = {
    mime: recorder.mimeType || mime || "audio/webm",
    startedAt,
    elapsed: () => Date.now() - startedAt,
    stop: () =>
      new Promise<RecordingResult>((resolve, reject) => {
        if (recorder.state === "inactive") {
          releaseMic()
          reject(new Error("录制已经结束了"))
          return
        }
        recorder.onstop = () => {
          releaseMic()
          const type = recorder.mimeType || mime || "audio/webm"
          const blob = new Blob(chunks, { type })
          if (!blob.size) {
            reject(new Error("没录到声音（可能麦克风选错了输入设备）"))
            return
          }
          resolve({ blob, durationMs: Date.now() - startedAt, mime: type })
        }
        recorder.stop()
      }),
    cancel: () => {
      try {
        if (recorder.state !== "inactive") recorder.stop()
      } catch {
        // 已经停了就算了
      }
      chunks.length = 0
      releaseMic()
    },
  }
  return session
}
