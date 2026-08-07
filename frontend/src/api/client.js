import axios from 'axios'
import uploadMock from '../mocks/upload.json'
import analyzeMock from '../mocks/analyze.json'

/**
 * Mock 开关（本地预览联调用）：
 * - 优先读取环境变量 VITE_USE_MOCK（'true' / 'false'）
 * - 未设置时默认使用 mock（true）
 * 接入真实后端时：设置 VITE_USE_MOCK=false，请求将走 vite proxy 的 /api → http://localhost:8000
 */
const USE_MOCK =
  import.meta.env.VITE_USE_MOCK !== undefined
    ? String(import.meta.env.VITE_USE_MOCK) === 'true'
    : true

export const isMockMode = () => USE_MOCK

const http = axios.create({ baseURL: '/api', timeout: 120000 })

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** 会话过期（后端 404）统一错误标识 */
export const SESSION_EXPIRED = 'SESSION_EXPIRED'

/**
 * POST /api/upload（FormData，字段 file）
 * 返回 { session_id, columns, preview_rows, auto_mapping, need_manual, warnings }
 */
export async function uploadFile(file) {
  if (USE_MOCK) {
    await delay(400)
    return JSON.parse(JSON.stringify(uploadMock))
  }
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post('/upload', form)
  return data
}

/**
 * POST /api/analyze（{ session_id, mapping }）
 * 返回 summary / performance / anomalies / growth
 */
export async function analyze(sessionId, mapping) {
  if (USE_MOCK) {
    await delay(600)
    return JSON.parse(JSON.stringify(analyzeMock))
  }
  try {
    const { data } = await http.post('/analyze', {
      session_id: sessionId,
      mapping
    })
    return data
  } catch (err) {
    if (err.response && err.response.status === 404) {
      const e = new Error('会话已过期，请重新上传')
      e.code = SESSION_EXPIRED
      throw e
    }
    throw err
  }
}

/**
 * GET /api/anomaly/default-prompt
 * 返回 { prompt } —— AI 异常分析默认提示词
 * （流式分析接口 /api/anomaly/stream 不走 axios，在 AiAnomalyPanel 内用 fetch + ReadableStream 实现）
 */
export async function getDefaultPrompt() {
  if (USE_MOCK) {
    await delay(100)
    return { prompt: '' }
  }
  const { data } = await http.get('/anomaly/default-prompt')
  return data
}
