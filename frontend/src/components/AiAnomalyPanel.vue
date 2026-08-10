<template>
  <div class="ai-anomaly-panel">
    <!-- Mock 模式：仅展示说明文字（无真实后端与大模型） -->
    <el-alert
      v-if="mockMode"
      type="info"
      :closable="false"
      show-icon
      title="当前为 Mock 预览模式"
      description="AI 数据分析需连接真实后端（VITE_USE_MOCK=false）并配置 backend/.env 中的 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 后方可使用。"
    />

    <template v-else>
      <!-- 提示词编辑区：改规则只改提示词 -->
      <div class="prompt-box">
        <!-- 提示词编辑面板（条件渲染） -->
        <div v-if="showPromptEditor" class="prompt-editor-panel" style="margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: 600; font-size: 14px; color: #5f6368;">系统提示词</span>
            <el-button type="success" size="small" :loading="loadingPrompt" :disabled="streaming || !prompt.trim()" @click="handleSavePrompt">
              保存提示词
            </el-button>
          </div>
          <el-input
            v-model="prompt"
            type="textarea"
            :autosize="{ minRows: 8, maxRows: 20 }"
            placeholder="请输入系统提示词..."
            :disabled="streaming || loadingPrompt"
            style="width: 100%;"
          />
          <div style="margin-top: 4px; font-size: 12px; color: #9aa0a6;">
            提示：修改提示词后，点击"保存提示词"将更新系统默认提示词。支持自定义分析维度、输出格式等。
          </div>
        </div>
        <div class="btn-bar">
          <el-button
            type="primary"
            :loading="loadingPrompt"
            :disabled="streaming || loadingPrompt || !prompt.trim()"
            @click="start"
          >
            {{ streaming ? '分析中…' : '开始分析' }}
          </el-button>
          <el-button v-if="streaming" type="danger" @click="stop">停止</el-button>
          <el-button :disabled="streaming || loadingPrompt" @click="resetPrompt">重置提示词</el-button>
          <el-button size="small" @click="showPromptEditor = !showPromptEditor">
            {{ showPromptEditor ? "收起提示词" : "编辑提示词" }}
          </el-button>
          <span v-if="streaming" class="muted">正在流式生成，可实时查看下方结果</span>
        </div>
      </div>

      <!-- 输出区 -->
      <div class="output-card">
        <div class="output-header">
          <span class="muted">分析结果</span>
          <div class="output-actions">
            <el-button size="small" :disabled="!fullText || streaming" @click="copyMd">复制</el-button>
            <el-button size="small" :disabled="!fullText || streaming" @click="exportToPDF">导出 PDF</el-button>
          </div>
        </div>

        <!-- 错误提示（配置缺失 / 模型调用失败 / 会话过期等） -->
        <el-alert v-if="errorMsg" type="error" :closable="false" :title="errorMsg" class="err-alert" />

        <!-- 加载占位 -->
        <div v-if="streaming && !fullText" class="loading-hint">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>模型正在分析数据，请稍候…</span>
        </div>

        <!-- Markdown 实时渲染区 -->
        <div class="md-body" v-html="renderedHtml"></div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { marked } from 'marked'
import html2canvas from 'html2canvas'
import { getDefaultPrompt, isMockMode, savePrompt } from '../api/client'

const props = defineProps({
  sessionId: { type: String, default: '' },  // 上传后获得的会话 ID
  startMonth: { type: String, default: '' }, // "YYYY-MM" 格式，如 "2025-10"
  endMonth: { type: String, default: '' },   // "YYYY-MM" 格式，如 "2026-07"
})
const emit = defineEmits(['session-expired'])

const mockMode = isMockMode()

// marked 配置：GFM 表格 + 换行
marked.setOptions({ gfm: true, breaks: true })

const prompt = ref('') // 提示词编辑区内容
const loadingPrompt = ref(false)
const streaming = ref(false) // 是否正在流式输出
const fullText = ref('') // 累积的 Markdown 原文
const errorMsg = ref('') // 错误信息
const showPromptEditor = ref(true) // 控制提示词编辑器显示/隐藏
let abortController = null // 用于"停止"按钮中断请求

// 拉取默认提示词（失败时保留空并提示）
async function loadDefaultPrompt() {
  loadingPrompt.value = true
  try {
    const data = await getDefaultPrompt()
    prompt.value = data.prompt || ''
  } catch (err) {
    ElMessage.error('获取默认提示词失败：' + (err.response?.data?.detail || err.message || '未知错误'))
  } finally {
    loadingPrompt.value = false
  }
}

// 重置提示词为默认值：先将当前编辑内容保存到后端 prompts.py，再重新加载
async function resetPrompt() {
  if (!prompt.value.trim()) {
    ElMessage.warning('提示词为空，无需保存')
    await loadDefaultPrompt()
    return
  }
  try {
    // 先保存当前提示词到后端 prompts.py
    await savePrompt(prompt.value)
    ElMessage.success('当前提示词已保存到 prompts.py')
  } catch (err) {
    ElMessage.error('保存提示词失败：' + (err.response?.data?.detail || err.message || '未知错误'))
    return // 保存失败则不继续重置
  }
  // 保存成功后，从后端重新加载（此时后端已更新）
  await loadDefaultPrompt()
}

/** 保存修改后的提示词 */
async function handleSavePrompt() {
  if (!prompt.value.trim()) {
    ElMessage.warning('提示词不能为空')
    return
  }
  loadingPrompt.value = true
  try {
    await savePrompt(prompt.value)
    ElMessage.success('提示词已保存')
  } catch (err) {
    ElMessage.error('保存失败：' + (err.response?.data?.detail || err.message || '未知错误'))
  } finally {
    loadingPrompt.value = false
  }
}

// 渲染：Markdown -> HTML；流式过程中追加打字光标
const renderedHtml = computed(() => {
  if (!fullText.value) return ''
  const html = marked.parse(fullText.value)
  return streaming.value ? html + '<span class="typing-cursor">▍</span>' : html
})

/** 构建流式分析请求体：包含会话ID、提示词和可选的时间范围 */
function buildRequestBody() {
  const body = { session_id: props.sessionId, prompt: prompt.value }
  // 仅在前端传入了有效时间范围时才附加，后端据此动态筛选数据
  if (props.startMonth) body.start_month = props.startMonth
  if (props.endMonth) body.end_month = props.endMonth
  return body
}

/** 发起 SSE 流式分析（fetch + ReadableStream 手动解析 SSE） */
async function start() {
  if (!props.sessionId) {
    ElMessage.error('缺少会话信息，请重新上传文件')
    emit('session-expired')
    return
  }
  errorMsg.value = ''
  fullText.value = ''
  streaming.value = true
  abortController = new AbortController()

  try {
    const resp = await fetch('/api/anomaly/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildRequestBody()),
      signal: abortController.signal
    })
    if (!resp.ok) {
      if (resp.status === 404) {
        errorMsg.value = '会话不存在或已过期，请重新上传文件'
        emit('session-expired')
      } else {
        errorMsg.value = '分析请求失败（HTTP ' + resp.status + '），请稍后重试'
      }
      return
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    // 逐块读取，按 SSE 事件分隔符 \n\n 切分处理
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() // 末尾可能是不完整片段，留到下一轮
      for (const part of parts) handleSseEvent(part)
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      errorMsg.value = fullText.value ? '已手动停止，以下为已生成内容' : '已停止分析'
    } else {
      errorMsg.value = '网络错误：' + (err.message || String(err))
    }
  } finally {
    streaming.value = false
    abortController = null
  }
}

/** 处理单个 SSE 事件块（可能包含多行 data:） */
function handleSseEvent(part) {
  for (const line of part.split('\n')) {
    if (!line.startsWith('data:')) continue
    let payload
    try {
      payload = JSON.parse(line.slice(5).trim())
    } catch (e) {
      continue // 跳过无法解析的行
    }
    if (payload.type === 'delta') {
      fullText.value += payload.content // 增量累加
    } else if (payload.type === 'warning') {
      ElMessage.warning(payload.message)
    } else if (payload.type === 'error') {
      errorMsg.value = payload.message || '分析失败'
    } else if (payload.type === 'done') {
      // 流正常结束（循环退出后 finally 会收尾）
    }
  }
}

/** 停止流式输出 */
function stop() {
  if (abortController) abortController.abort()
}

/** 复制原始 Markdown 文本 */
async function copyMd() {
  try {
    await navigator.clipboard.writeText(fullText.value)
    ElMessage.success('已复制到剪贴板')
  } catch (e) {
    // 降级方案：非 HTTPS 或权限受限时用 execCommand
    const ta = document.createElement('textarea')
    ta.value = fullText.value
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    ElMessage.success('已复制到剪贴板')
  }
}

/** 通用 Blob 下载 */
function downloadBlob(content, filename, mime) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** 下载原始 Markdown */
function downloadMd() {
  downloadBlob(fullText.value, '异常分析结果.md', 'text/markdown;charset=utf-8')
}

/** 导出分析结果为 PDF（通过打印对话框另存为） */
function exportToPDF() {
  const mdBody = document.querySelector('.md-body')
  if (!mdBody || !mdBody.innerHTML.trim()) {
    ElMessage.warning('暂无分析结果可导出')
    return
  }
  const printWindow = window.open('', '_blank')
  if (!printWindow) {
    ElMessage.error('请允许弹出窗口以导出 PDF')
    return
  }
  const html = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>AI 数据分析报告</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;font-size:14px;line-height:1.6;color:#202124;padding:20px;max-width:900px;margin:0 auto}
h1,h2,h3{color:#1a73e8}
h1{font-size:20px;border-bottom:2px solid #1a73e8;padding-bottom:8px}
h2{font-size:16px;margin-top:20px}
h3{font-size:14px}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13px}
th{background:#f8f9fa;padding:8px 10px;font-weight:600;border:1px solid #dadce0;text-align:left;color:#5f6368}
td{padding:6px 10px;border:1px solid #dadce0}
tr:nth-child(even){background:#fafbfc}
strong{color:#202124}
em{color:#5f6368}
hr{border:none;border-top:1px solid #e8eaed;margin:16px 0}
p{margin:8px 0}
ul,ol{margin:8px 0;padding-left:24px}
li{margin:4px 0}
code{background:#f1f3f4;padding:2px 6px;border-radius:3px;font-size:13px}
blockquote{border-left:3px solid #1a73e8;padding-left:12px;color:#5f6368;margin:12px 0}
@media print{body{padding:10px}table{page-break-inside:avoid}}
</style></head><body>
<h1>AI 数据分析报告</h1>
<p style="color:#9aa0a6;font-size:12px">生成时间：${new Date().toLocaleString('zh-CN')}</p>
<hr>
${mdBody.innerHTML}
</body></html>`
  printWindow.document.write(html)
  printWindow.document.close()
  setTimeout(() => { printWindow.print(); printWindow.close() }, 500)
  ElMessage.success('PDF 导出已启动，请在打印对话框中选择"另存为 PDF"')
}


/**
 * 从 Markdown 文本中提取所有表格（连续的 | 行块，且第二行为分隔行）
 * 返回 string[][]，每个元素是一张表的原始行（不含分隔行）
 */
function extractMarkdownTables(md) {
  const lines = md.split('\n')
  const tables = []
  const isSep = (s) => /^\|?[\s:|-]+\|?$/.test(s) && s.includes('-')
  let i = 0
  while (i < lines.length) {
    const first = lines[i].trim()
    const second = i + 1 < lines.length ? lines[i + 1].trim() : ''
    if (first.includes('|') && isSep(second)) {
      const rows = []
      while (i < lines.length && lines[i].trim().includes('|')) {
        if (!isSep(lines[i].trim())) rows.push(lines[i].trim())
        i++
      }
      if (rows.length) tables.push(rows)
    } else {
      i++
    }
  }
  return tables
}

/** Markdown 表格行 -> 单元格数组（去掉加粗标记） */
function mdRowToCells(row) {
  let s = row.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|')) s = s.slice(0, -1)
  return s.split('|').map((c) => c.trim().replace(/\*\*/g, ''))
}

/** CSV 字段转义 */
function csvEscape(cell) {
  if (/[",\n]/.test(cell)) return '"' + cell.replace(/"/g, '""') + '"'
  return cell
}

// ===== 逐表下载：为每个渲染后的 <table> 添加浮动操作栏 =====

/** 从表格上方的标题元素提取表名，若无则用默认名 */
function getTableName(tableEl, tableIndex) {
  // 向上查找最近的同级/父级 h1~h3 标题
  let prev = tableEl.previousElementSibling
  while (prev) {
    if (/^H[1-3]$/.test(prev.tagName)) {
      return prev.textContent.trim() || ''
    }
    prev = prev.previousElementSibling
  }
  // 尝试在父容器内查找
  const parent = tableEl.parentElement
  if (parent) {
    const headings = parent.querySelectorAll('h1, h2, h3')
    for (const h of headings) {
      // 取在表格之前且最靠近表格的标题
      if (h.compareDocumentPosition(tableEl) & Node.DOCUMENT_POSITION_FOLLOWING) {
        return h.textContent.trim() || ''
      }
    }
  }
  return ''
}

/** 将 HTML <table> 解析为二维数组 */
function tableToArray(tableEl) {
  const rows = []
  for (const tr of tableEl.querySelectorAll('tr')) {
    const cells = []
    for (const td of tr.querySelectorAll('th, td')) {
      cells.push(td.textContent.trim())
    }
    rows.push(cells)
  }
  return rows
}

/** 单表 CSV 下载（带 BOM，UTF-8） */
function downloadTableCsv(tableEl, tableIndex) {
  const name = getTableName(tableEl, tableIndex) || ('table_' + (tableIndex + 1))
  const rows = tableToArray(tableEl)
  if (!rows.length) {
    ElMessage.warning('表格数据为空，无法下载')
    return
  }
  const csvContent = rows.map(r => r.map(csvEscape).join(',')).join('\n')
  // 文件名：用表名 + 序号
  const safeName = name.replace(/[\\/:*?"<>|]/g, '_').slice(0, 50)
  const filename = '表' + (tableIndex + 1) + '_' + safeName + '.csv'
  downloadBlob('\uFEFF' + csvContent, filename, 'text/csv;charset=utf-8')
  ElMessage.success('CSV 已开始下载：' + filename)
}

/** 单表 PNG 下载（html2canvas 截图） */
async function downloadTablePng(tableEl, tableIndex) {
  const name = getTableName(tableEl, tableIndex) || ('table_' + (tableIndex + 1))
  const safeName = name.replace(/[\\/:*?"<>|]/g, '_').slice(0, 50)
  const filename = '表' + (tableIndex + 1) + '_' + safeName + '.png'
  try {
    const canvas = await html2canvas(tableEl, {
      backgroundColor: '#ffffff',
      scale: 2, // 高清输出
      useCORS: true,
    })
    const url = canvas.toDataURL('image/png')
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    ElMessage.success('PNG 已开始下载：' + filename)
  } catch (err) {
    console.error('表格截图失败:', err)
    ElMessage.error('PNG 截图失败：' + (err.message || '未知错误'))
  }
}

// CSV/PNG 下载按钮已移除（需求变更）

// CSV/PNG 工具栏注入已移除

onMounted(() => {
  if (!mockMode) loadDefaultPrompt()
})
onBeforeUnmount(() => {
  // 离开页面时中断未完成的流式请求
  if (abortController) abortController.abort()
})
</script>

<style scoped>
.ai-anomaly-panel {
  font-size: var(--fs-base);
}
.ai-anomaly-panel .prompt-section {
  background: var(--bg-hover);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
  margin-bottom: var(--spacing-md);
}
.ai-anomaly-panel .md-body {
  background: var(--bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  padding: var(--spacing-lg);
  min-height: 200px;
  font-size: var(--fs-base);
  line-height: 1.8;
}
/* 表格样式 */
.md-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  border: 1px solid #dadce0;
  font-size: 14px;
}
.md-body th {
  background: #f8f9fa;
  padding: 10px 12px;
  font-weight: 600;
  font-size: 13px;
  color: #5f6368;
  border: 1px solid #dadce0;
  text-align: left;
}
.md-body td {
  padding: 8px 12px;
  border: 1px solid #dadce0;
  font-size: 14px;
  color: #202124;
}
.md-body tr:nth-child(even) {
  background: #fafbfc;
}
.md-body tr:hover {
  background: #e8f0fe;
}
.ai-anomaly-panel .action-bar {
  display: flex;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);
  flex-wrap: wrap;
}
</style>
