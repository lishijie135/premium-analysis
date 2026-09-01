import axios from 'axios'
import JSEncrypt from 'jsencrypt'
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

// ---- 登录态（Token）管理 ----
const TOKEN_KEY = 'pa_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

// 鉴权失败后由 App 注册回调，统一跳回登录页
let authFailHandler = null
export function onAuthFail(fn) {
  authFailHandler = fn
}

const http = axios.create({ baseURL: '/api', timeout: 120000 })

// 请求拦截器：自动附加 Bearer Token
http.interceptors.request.use((config) => {
  const t = getToken()
  if (t) config.headers.Authorization = `Bearer ${t}`
  return config
})

// 响应拦截器：401（未登录 / Token 失效）统一清除并跳回登录
http.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response && err.response.status === 401) {
      clearToken()
      if (authFailHandler) authFailHandler()
    }
    return Promise.reject(err)
  }
)

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

/**
 * POST /api/anomaly/save-prompt
 * 保存用户编辑的提示词到后端 prompts.py 的 DEFAULT_PROMPT
 * 请求体: { prompt: "提示词内容" }
 * 返回: { success: true, message: "提示词已保存" }
 */
export async function savePrompt(promptText) {
  if (USE_MOCK) {
    await delay(100)
    return { success: true, message: 'Mock 模式：提示词已保存（模拟）' }
  }
  const { data } = await http.post('/anomaly/save-prompt', {
    prompt: promptText
  })
  return data
}


// ---- 可配置规则引擎 API ----

/**
 * 获取规则配置
 * GET /api/anomaly/rules-config
 */
export async function getRulesConfig() {
  if (USE_MOCK) {
    await delay(100)
    return {
      version: '1.0',
      global: { min_policies: 2, drop_rate: 0.30 },
      tables: [
        {
          id: 'q2_vs_q1',
          name: 'Mock 规则 1',
          enabled: true,
          type: 'period_compare',
          base_period: { year: 2026, months: [1, 2, 3] },
          curr_period: { year: 2026, months: [4, 5, 6] },
          thresholds: { premium_drop_pct: -30, policies_drop_pct: -30 }
        }
      ]
    }
  }
  const { data } = await http.get('/anomaly/rules-config')
  return data
}

/**
 * 执行规则引擎分析
 * POST /api/anomaly/rules-analyze
 */
export async function runRulesAnalyze(sessionId) {
  if (USE_MOCK) {
    await delay(600)
    return {
      tables: [
        {
          id: 'mock1',
          name: 'Mock 分析结果',
          columns: ['客户代码', '保费环比%'],
          rows: [{ '客户代码': 'C001', '保费环比%': '-35.5%' }],
          summary: '共识别 1 家异常客户'
        }
      ]
    }
  }
  const { data } = await http.post('/anomaly/rules-analyze', { session_id: sessionId })
  return data
}

/**
 * 保存规则配置
 * PUT /api/anomaly/rules-config
 */
export async function saveRulesConfig(config) {
  if (USE_MOCK) {
    await delay(100)
    return { success: true, message: 'Mock 保存成功' }
  }
  const { data } = await http.put('/anomaly/rules-config', config)
  return data
}

/**
 * 获取规则分析导出 URL
 * @param {string} sessionId - 会话 ID
 * @param {string} tableId - 表 ID
 * @param {string} format - 导出格式 (csv/excel)
 */
export function getRulesExportUrl(sessionId, tableId, format) {
  return '/api/anomaly/rules-export?session_id=' + sessionId + '&table_id=' + tableId + '&format=' + format
}

/**
 * 清空 AI 对话历史
 * POST /api/chat/clear
 * @param {string} sessionId - 会话 ID
 */
export async function clearChat(sessionId) {
  if (USE_MOCK) {
    await delay(200)
    console.log('[client.js] Mock 模式：清空对话历史（本地模拟）')
    return
  }
  await http.post('/chat/clear', { session_id: sessionId })
}

/**
 * 自动优化提示词
 * @param {string} prompt - 当前提示词内容
 * @returns {Promise<{prompt: string}>} 优化后的提示词
 */
export async function optimizePrompt(prompt) {
  if (USE_MOCK) {
    await delay(1500)
    return { prompt: prompt + '\n\n[Mock 模式：提示词已自动优化]' }
  }
  const { data } = await http.post('/anomaly/optimize-prompt', { prompt })
  return data
}

// ---- 提示词模板管理 API ----

/**
 * 获取所有提示词模板列表
 * @returns {Promise<{templates: Array<{id: string, name: string, active: boolean}>}>}
 */
export async function getTemplates() {
  if (USE_MOCK) {
    await delay(300)
    return {
      templates: [
        { id: "default", name: "默认模板", active: true },
        { id: "mock2", name: "季度分析模板", active: false }
      ]
    }
  }
  const { data } = await http.get('/anomaly/templates')
  return data
}

/**
 * 获取单个模板详情
 * @param {string} templateId - 模板 ID
 * @returns {Promise<{id: string, name: string, content: string}>}
 */
export async function getTemplate(templateId) {
  if (USE_MOCK) {
    await delay(200)
    return { id: templateId, name: "Mock 模板", content: "Mock 提示词内容" }
  }
  const { data } = await http.get(`/anomaly/templates/${templateId}`)
  return data
}

/**
 * 创建新提示词模板
 * @param {string} name - 模板名称
 * @param {string} content - 提示词内容
 * @returns {Promise<{id: string, name: string, content: string}>}
 */
export async function createTemplate(name, content) {
  if (USE_MOCK) {
    await delay(500)
    return { id: "mock_" + Date.now(), name, content }
  }
  const { data } = await http.post('/anomaly/templates', { name, content })
  return data
}

/**
 * 更新提示词模板
 * @param {string} templateId - 模板 ID
 * @param {string} name - 模板名称
 * @param {string} content - 提示词内容
 * @returns {Promise<{id: string, name: string, content: string}>}
 */
export async function updateTemplate(templateId, name, content) {
  if (USE_MOCK) {
    await delay(300)
    return { id: templateId, name, content }
  }
  const { data } = await http.put(`/anomaly/templates/${templateId}`, { name, content })
  return data
}

/**
 * 删除提示词模板
 * @param {string} templateId - 模板 ID
 * @returns {Promise<{success: boolean}>}
 */
export async function deleteTemplate(templateId) {
  if (USE_MOCK) {
    await delay(300)
    return { success: true }
  }
  const { data } = await http.delete(`/anomaly/templates/${templateId}`)
  return data
}

/**
 * 设置当前激活的模板
 * @param {string} templateId - 模板 ID
 * @returns {Promise<{success: boolean}>}
 */
export async function activateTemplate(templateId) {
  if (USE_MOCK) {
    await delay(200)
    return { success: true }
  }
  const { data } = await http.post(`/anomaly/templates/${templateId}/activate`)
  return data
}

// ---- 登录认证 API ----

let _pubKeyCache = null

/**
 * 获取 RSA 公钥（带缓存），用于前端加密登录密码。
 * 后端部署为 HTTP，浏览器 crypto.subtle 在非安全上下文不可用，
 * 故使用 jsencrypt（纯 JS RSA，PKCS1 v1.5）加密。
 */
export async function getRsaPublicKey() {
  if (_pubKeyCache) return _pubKeyCache
  const { data } = await http.get('/auth/rsa-public-key')
  _pubKeyCache = data.public_key
  return _pubKeyCache
}

/**
 * 登录：RSA 加密密码后提交，成功写入 Token。
 * @param {string} username - 用户名（手机号）
 * @param {string} password - 明文密码（仅在本地加密，明文不离开浏览器）
 * @returns {Promise<{token: string, username: string, expires_in: number}>}
 */
export async function login(username, password) {
  const pub = await getRsaPublicKey()
  const crypt = new JSEncrypt()
  crypt.setPublicKey(pub)
  const enc = crypt.encrypt(password)
  if (!enc) {
    throw new Error('密码加密失败，请刷新页面重试')
  }
  const { data } = await http.post('/auth/login', { username, enc })
  setToken(data.token)
  return data
}

/**
 * 登出：通知后端（无状态，可选）并清除本地 Token。
 */
export async function logout() {
  try {
    await http.post('/auth/logout')
  } catch (e) {
    // 忽略网络错误，本地清除即可
  }
  clearToken()
}
