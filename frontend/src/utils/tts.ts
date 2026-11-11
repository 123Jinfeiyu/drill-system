/**
 * 浏览器语音合成（Web Speech API）封装 —— 没有真人录音时的兜底。
 *
 * 实战场景的三条约束决定了这里的写法：
 *
 * 1. **必须能被打断**：客户随时会接着说，坐席点下一条就得立刻换声。
 *    所以每次播报都带一个 token，取消后旧的回调一律丢弃。
 * 2. **音色要稳定**：中文语音列表在不同机器上顺序不同，不主动挑就会随机变成
 *    英文腔。这里优先选 zh-CN 的女性音色，并把结果缓存住。
 * 3. **文本要洗**：话术里带 `~`、颜文字 `(*＾-＾*)`、表情符号，直接念会很怪。
 */

const EMOJI =
  /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{200D}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}]/gu

let cachedVoice: SpeechSynthesisVoice | null = null
let voicesReady: Promise<void> | null = null

export function ttsSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window
}

/** 语音列表是异步加载的，第一次可能为空，这里等一次 voiceschanged。 */
function prepareVoices(): Promise<void> {
  if (!ttsSupported()) return Promise.resolve()
  if (voicesReady) return voicesReady
  voicesReady = new Promise<void>((resolve) => {
    const synth = window.speechSynthesis
    if (synth.getVoices().length) {
      resolve()
      return
    }
    let settled = false
    const done = () => {
      if (settled) return
      settled = true
      synth.removeEventListener("voiceschanged", done)
      resolve()
    }
    synth.addEventListener("voiceschanged", done)
    // 某些内核不触发 voiceschanged，别把调用方永久挂住
    window.setTimeout(done, 1200)
  })
  return voicesReady
}

function pickVoice(): SpeechSynthesisVoice | null {
  if (cachedVoice) return cachedVoice
  const voices = window.speechSynthesis.getVoices()
  if (!voices.length) return null
  const zh = voices.filter((v) => /^zh/i.test(v.lang) || /Chinese|中文|普通话/i.test(v.name))
  const pool = zh.length ? zh : voices
  const preferred =
    pool.find((v) => /zh[-_]CN/i.test(v.lang) && /female|女|Xiaoxiao|Huihui|Yaoyao|Tingting/i.test(v.name)) ??
    pool.find((v) => /zh[-_]CN/i.test(v.lang)) ??
    pool[0]
  cachedVoice = preferred ?? null
  return cachedVoice
}

/** 洗掉念不出来或念起来很怪的部分。 */
export function sanitizeForSpeech(text: string): string {
  return text
    .replace(EMOJI, "")
    .replace(/[（(][^)）]{0,12}[)）]/g, (m) => (/\d|银行|客服|平台|账户/.test(m) ? m : ""))
    .replace(/[~\u301C\uFF5E]+/g, "，")
    .replace(/_{2,}|-{3,}/g, "，")
    .replace(/\s+/g, "")
    .replace(/[，、]{2,}/g, "，")
    .replace(/^[，。！？、]+|[，、]+$/g, "")
    .trim()
}

export interface SpeakOptions {
  rate?: number
  volume?: number
  onStart?: () => void
  onEnd?: () => void
  onError?: (message: string) => void
}

let activeToken = 0

/** 播报一段文本；返回本次播报的 token，可用于判断是否已被打断。 */
export function speak(text: string, options: SpeakOptions = {}): number {
  const token = ++activeToken
  if (!ttsSupported()) {
    options.onError?.("当前浏览器不支持语音合成，请改用真人录音")
    return token
  }
  const spoken = sanitizeForSpeech(text)
  if (!spoken) {
    options.onError?.("这段内容没有可播报的文字")
    return token
  }
  void prepareVoices().then(() => {
    if (token !== activeToken) return // 已被下一条或停止打断
    const synth = window.speechSynthesis
    try {
      synth.cancel()
    } catch {
      /* 某些内核 cancel 会抛，忽略即可 */
    }
    const utterance = new SpeechSynthesisUtterance(spoken)
    const voice = pickVoice()
    if (voice) utterance.voice = voice
    utterance.lang = voice?.lang || "zh-CN"
    utterance.rate = options.rate ?? 1
    utterance.volume = options.volume ?? 1
    utterance.onstart = () => {
      if (token === activeToken) options.onStart?.()
    }
    utterance.onend = () => {
      if (token === activeToken) options.onEnd?.()
    }
    utterance.onerror = (event) => {
      if (token !== activeToken) return
      if (event.error === "interrupted" || event.error === "canceled") return
      options.onError?.(`语音合成失败：${event.error}`)
    }
    synth.speak(utterance)
  })
  return token
}

/** 停止播报（并使所有在途回调失效）。 */
export function stopSpeaking(): void {
  activeToken += 1
  if (!ttsSupported()) return
  try {
    window.speechSynthesis.cancel()
  } catch {
    /* 忽略 */
  }
}

export function isSpeaking(): boolean {
  return ttsSupported() && window.speechSynthesis.speaking
}

/** 页面卸载时清干净，否则某些内核会把上一次的语音带进下一次会话。 */
export function releaseTts(): void {
  stopSpeaking()
  cachedVoice = null
  voicesReady = null
}
