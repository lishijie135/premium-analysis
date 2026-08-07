<template>
  <div>
    <!-- Mock 模式：仅展示说明文字（无真实后端与大模型） -->
    <el-alert
      v-if="mockMode"
      type="info"
      :closable="false"
      show-icon
      title="当前为 Mock 预览模式"
      description="AI 异常分析需连接真实后端（VITE_USE_MOCK=false）并配置 backend/.env 中的 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 后方可使用。"
    />

    <template v-else>
      <!-- 提示词编辑区：改规则只改提示词 -->
      <div class="prompt-box">
        <el-input
          v-model="prompt"
          type="textarea"
          :autosize="{ minRows: 8, maxRows: 20 }"
          placeholder="加载中…"
          :disabled="streaming || loadingPrompt"
        />
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
          <span v-if="streaming" class="muted">正在流式生成，可实时查看下方结果</span>
        </div>
      </div>

      <!-- 输出区 -->
      <div class="output-card">
        <div class="output-header">
          <span class="muted">分析结果</span>
          <div class="output-actions">
            <el-button size="small" :disabled="!fullText || streaming" @click="copyMd">复制</el-button>
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
import { getDefaultPrompt, isMockMode } from '../api/client'

const props = defineProps({
  sessionId: { type: String, default: '' } // 上传后获得的会话 ID
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

// 重置提示词为默认值
async function resetPrompt() {
  await loadDefaultPrompt()
  ElMessage.success('已重置为默认提示词')
}

// 渲染：Markdown -> HTML；流式过程中追加打字光标
const renderedHtml = computed(() => {
  if (!fullText.value) return ''
  const html = marked.parse(fullText.value)
  return streaming.value ? html + '<span class="typing-cursor">▍</span>' : html
})

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
      body: JSON.stringify({ session_id: props.sessionId, prompt: prompt.value }),
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

/** 为渲染区所有表格注入浮动操作栏 */
function attachTableToolbars() {
  const mdBody = document.querySelector('.md-body')
  if (!mdBody) return
  const tables = mdBody.querySelectorAll('table')
  if (!tables.length) return

  tables.forEach((tableEl, idx) => {
    // 避免重复注入
    if (tableEl.dataset.toolbarAttached === 'true') return
    tableEl.dataset.toolbarAttached = 'true'

    // 包裹表格，使其可以相对定位操作栏
    const wrapper = document.createElement('div')
    wrapper.className = 'table-wrapper'
    wrapper.style.position = 'relative'
    wrapper.style.display = 'inline-block'
    wrapper.style.width = '100%'

    // 创建浮动操作栏
    const toolbar = document.createElement('div')
    toolbar.className = 'table-toolbar'
    toolbar.innerHTML = `
      <button class="toolbar-btn" title="下载 CSV">CSV</button>
      <button class="toolbar-btn" title="下载 PNG">PNG</button>
    `
    // 绑定事件
    const [csvBtn, pngBtn] = toolbar.querySelectorAll('.toolbar-btn')
    csvBtn.addEventListener('click', (e) => {
      e.stopPropagation()
      downloadTableCsv(tableEl, idx)
    })
    pngBtn.addEventListener('click', (e) => {
      e.stopPropagation()
      downloadTablePng(tableEl, idx)
    })

    // 将表格包裹起来
    tableEl.parentNode.insertBefore(wrapper, tableEl)
    wrapper.appendChild(tableEl)
    wrapper.appendChild(toolbar)
  })
}

// 监听 renderedHtml 变化，渲染完成后注入操作栏
watch(renderedHtml, () => {
  nextTick(() => {
    attachTableToolbars()
  })
})

onMounted(() => {
  if (!mockMode) loadDefaultPrompt()
})
onBeforeUnmount(() => {
  // 离开页面时中断未完成的流式请求
  if (abortController) abortController.abort()
})
</script>

<style scoped>
.prompt-box {
  margin-bottom: calc(var(--fs-base) * 1);
}
.btn-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}
.output-card {
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 6px;
  padding: 12px 16px;
  min-height: 180px;
}
.output-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.err-alert {
  margin-bottom: 10px;
}
.loading-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #909399;
  padding: 8px 0;
}
/* Markdown 渲染区：表格边框 + 斑马纹 */
.md-body :deep(table) {
  border-collapse: collapse;
  margin: 12px 0;
  font-size: calc(var(--fs-base) * 0.9);
}
.md-body :deep(th),
.md-body :deep(td) {
  border: 1px solid #dcdfe6;
  padding: 6px 10px;
  text-align: left;
}
.md-body :deep(th) {
  background: #f0f2f5;
}
.md-body :deep(tr:nth-child(even)) {
  background: #f7f8fa;
}
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3) {
  margin: 12px 0 8px;
}
/* 打字光标 */
.md-body :deep(.typing-cursor) {
  display: inline-block;
  animation: cursor-blink 1s steps(1) infinite;
  color: #409eff;
}
@keyframes cursor-blink {
  50% {
    opacity: 0;
  }
}
/* 逐表下载操作栏 */
.table-wrapper {
  position: relative;
  display: inline-block;
  width: 100%;
}
.table-toolbar {
  position: absolute;
  top: 4px;
  right: 4px;
  display: flex;
  gap: 4px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  padding: 3px 5px;
  opacity: 0;
  transition: opacity 0.2s ease;
  z-index: 10;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}
.table-wrapper:hover .table-toolbar {
  opacity: 1;
}
.toolbar-btn {
  font-size: 11px;
  line-height: 1;
  padding: 3px 7px;
  border: 1px solid #dcdfe6;
  border-radius: 3px;
  background: #f5f7fa;
  color: #606266;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}
.toolbar-btn:hover {
  background: #409eff;
  color: #fff;
  border-color: #409eff;
}
</style>
