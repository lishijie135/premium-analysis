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
      <!-- 提示词模板管理区 -->
      <div class="prompt-box">
        <!-- 区域1：模板标签栏 -->
        <div class="template-tab-bar">
          <div class="template-tabs">
            <div
              v-for="t in templates" :key="t.id"
              class="template-tab"
              :class="{ active: t.id === activeTemplateId }"
              @click="switchTemplate(t.id)"
              :title="t.name"
            >
              <span class="tab-name">{{ t.name }}</span>
              <span
                v-if="templates.length > 1"
                class="tab-delete"
                @click.stop="handleDeleteTemplate(t.id)"
                title="删除模板"
              >&times;</span>
            </div>
            <!-- 新建模板按钮 -->
            <div class="template-tab template-tab-add" @click="showNewTemplateInput = true" title="新建模板">
              <span class="tab-add-icon">+</span>
            </div>
          </div>
        </div>

        <!-- 新建模板输入行 -->
        <div v-if="showNewTemplateInput" class="new-template-input-row">
          <el-input v-model="newTemplateName" placeholder="输入模板名称" size="small" style="width: 200px;" @keyup.enter="handleCreateTemplate" />
          <el-button type="success" size="small" @click="handleCreateTemplate" :loading="loadingPrompt">确认</el-button>
          <el-button size="small" @click="showNewTemplateInput = false; newTemplateName = ''">取消</el-button>
        </div>

        <!-- 区域2：提示词编辑器（始终展开） -->
        <div class="prompt-editor-panel">
          <div class="editor-header">
            <span class="editor-title">
              编辑：{{ templates.find(t => t.id === activeTemplateId)?.name || '提示词' }}
            </span>
            <div class="editor-actions">
              <el-button type="success" size="small" :loading="loadingPrompt" :disabled="streaming || !prompt.trim()" @click="handleSavePrompt">
                保存提示词
              </el-button>
              <el-button type="warning" size="small" :loading="optimizingPrompt" :disabled="streaming || optimizingPrompt || !prompt.trim()" @click="handleOptimizePrompt">
                <el-icon><MagicStick /></el-icon>
                <span>一键优化</span>
              </el-button>
            </div>
          </div>
          <el-input
            v-model="prompt"
            type="textarea"
            :autosize="{ minRows: 8, maxRows: 20 }"
            placeholder="请输入系统提示词..."
            :disabled="streaming || loadingPrompt"
            style="width: 100%;"
          />
          <div class="editor-hint">
            提示：修改提示词后，点击"保存提示词"将更新当前模板
          </div>
        </div>

        <!-- 区域3：开始分析按钮 -->
        <div class="analyze-action-row">
          <el-button
            type="primary"
            :loading="loadingPrompt"
            :disabled="streaming || loadingPrompt || !prompt.trim()"
            @click="start"
          >
            {{ streaming ? '分析中…' : '开始分析' }}
          </el-button>
          <el-button v-if="streaming" type="danger" @click="stop">停止</el-button>
          <span v-if="streaming" class="muted" style="margin-left: 8px;">正在流式生成…</span>
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, MagicStick } from '@element-plus/icons-vue'
import { marked } from 'marked'
import html2canvas from 'html2canvas'
import { getDefaultPrompt, isMockMode, savePrompt, optimizePrompt, getTemplates, getTemplate, createTemplate, updateTemplate, deleteTemplate, activateTemplate } from '../api/client'

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
const optimizingPrompt = ref(false) // 提示词优化中
let abortController = null // 用于"停止"按钮中断请求

// ---- 多模板管理状态 ----
const templates = ref([]) // 模板列表 [{id, name, active}]
const activeTemplateId = ref('') // 当前激活的模板 ID
const editingTemplateId = ref('') // 正在编辑的模板 ID
const newTemplateName = ref('') // 新建模板名称
const showNewTemplateInput = ref(false) // 显示新建模板输入框
const loadingTemplates = ref(false) // 模板列表加载中

// 加载模板列表
async function loadTemplates() {
  loadingTemplates.value = true
  try {
    const res = await getTemplates()
    templates.value = res.templates || []
    const active = templates.value.find(t => t.active)
    if (active) {
      activeTemplateId.value = active.id
      await loadActiveTemplate()
    }
  } catch (err) {
    ElMessage.error('获取模板列表失败：' + (err.message || '未知错误'))
  } finally {
    loadingTemplates.value = false
  }
}

// 加载当前激活模板的内容
async function loadActiveTemplate() {
  if (!activeTemplateId.value) return
  loadingPrompt.value = true
  try {
    const t = await getTemplate(activeTemplateId.value)
    prompt.value = t.content || ''
    editingTemplateId.value = t.id
  } catch (err) {
    ElMessage.error('获取模板内容失败：' + (err.message || '未知错误'))
  } finally {
    loadingPrompt.value = false
  }
}

// 拉取默认提示词（向后兼容）
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

/** 保存修改后的提示词到当前模板 */
async function handleSavePrompt() {
  if (!prompt.value.trim()) {
    ElMessage.warning('提示词不能为空')
    return
  }
  loadingPrompt.value = true
  try {
    if (editingTemplateId.value) {
      // 更新现有模板
      const t = templates.value.find(t => t.id === editingTemplateId.value)
      await updateTemplate(editingTemplateId.value, t?.name || '未命名', prompt.value)
      ElMessage.success('提示词已保存到当前模板')
    } else {
      // 向后兼容：保存到默认位置
      await savePrompt(prompt.value)
      ElMessage.success('提示词已保存')
    }
    await loadTemplates() // 刷新模板列表
  } catch (err) {
    ElMessage.error('保存失败：' + (err.message || '未知错误'))
  } finally {
    loadingPrompt.value = false
  }
}

/** 切换到指定模板 */
async function switchTemplate(templateId) {
  if (templateId === activeTemplateId.value) return
  try {
    await activateTemplate(templateId)
    activeTemplateId.value = templateId
    editingTemplateId.value = templateId
    await loadActiveTemplate()
  } catch (err) {
    ElMessage.error('切换模板失败：' + (err.message || '未知错误'))
  }
}

/** 新建模板 */
async function handleCreateTemplate() {
  if (!newTemplateName.value.trim()) {
    ElMessage.warning('请输入模板名称')
    return
  }
  loadingPrompt.value = true
  try {
    const t = await createTemplate(newTemplateName.value.trim(), prompt.value)
    templates.value.push({ id: t.id, name: t.name, active: false })
    newTemplateName.value = ''
    showNewTemplateInput.value = false
    ElMessage.success('模板已创建')
    await loadTemplates()
  } catch (err) {
    ElMessage.error('创建模板失败：' + (err.message || '未知错误'))
  } finally {
    loadingPrompt.value = false
  }
}

/** 删除模板 */
async function handleDeleteTemplate(templateId) {
  if (templates.value.length <= 1) {
    ElMessage.warning('至少保留一个模板')
    return
  }
  try {
    await ElMessageBox.confirm('确定要删除此模板吗？', '确认删除', { type: 'warning' })
    await deleteTemplate(templateId)
    templates.value = templates.value.filter(t => t.id !== templateId)
    if (templateId === activeTemplateId.value) {
      await loadTemplates()
    }
    ElMessage.success('模板已删除')
  } catch (err) {
    if (err !== 'cancel') {
      ElMessage.error('删除模板失败：' + (err.message || '未知错误'))
    }
  }
}

/** 自动优化提示词 */
async function handleOptimizePrompt() {
  if (!prompt.value.trim()) {
    ElMessage.warning('请先输入提示词内容')
    return
  }
  optimizingPrompt.value = true
  try {
    const res = await optimizePrompt(prompt.value)
    prompt.value = res.prompt
    ElMessage.success('提示词已自动优化')
  } catch (err) {
    ElMessage.error('优化失败：' + (err.message || '未知错误'))
  } finally {
    optimizingPrompt.value = false
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
  if (!mockMode) loadTemplates()
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

/* ---- 模板标签栏 ---- */
.template-tab-bar {
  margin-bottom: 12px;
}
.template-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.template-tab {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 12px;
  height: 32px;
  border-radius: 4px;
  border: 1px solid #e0e0e0;
  background: #f5f5f5;
  color: #5f6368;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
  max-width: 160px;
  user-select: none;
}
.template-tab:hover {
  background: #e8eaed;
}
.template-tab.active {
  background: #1a73e8;
  color: #fff;
  border-color: #1a73e8;
  font-weight: 600;
}
.template-tab.active:hover {
  background: #1565c0;
}
.template-tab .tab-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 120px;
}
.template-tab .tab-delete {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  font-size: 14px;
  line-height: 1;
  color: inherit;
  opacity: 0;
  transition: opacity 0.15s, background 0.15s, color 0.15s;
  flex-shrink: 0;
}
/* hover 模板标签时，删除按钮淡入显示 */
.template-tab:hover .tab-delete {
  opacity: 0.7;
}
.template-tab .tab-delete:hover {
  opacity: 1 !important;
  background: rgba(217, 48, 49, 0.15);
  color: #d93025;
}
.template-tab.active .tab-delete:hover {
  background: rgba(255,255,255,0.2);
}

/* ---- 新建模板输入行 ---- */
.new-template-input-row {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  align-items: center;
}

/* ---- 编辑器面板 ---- */
.prompt-editor-panel {
  margin-bottom: 16px;
}
.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.editor-title {
  font-weight: 600;
  font-size: 14px;
  color: #5f6368;
}
.editor-actions {
  display: flex;
  gap: 8px;
}
.editor-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #9aa0a6;
}

/* ---- 操作按钮区域 ---- */
.template-tab-add {
  border-style: dashed;
  background: transparent;
  color: #9aa0a6;
}
.template-tab-add:hover {
  border-color: #1a73e8;
  color: #1a73e8;
  background: rgba(26, 115, 232, 0.04);
}
.template-tab-add .tab-add-icon {
  font-size: 18px;
  font-weight: 300;
  line-height: 1;
}
.analyze-action-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 4px;
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
  font-size: 14px;
  line-height: 1.8;
  color: #202124;
  word-break: break-word;
}
.md-body h1, .md-body h2, .md-body h3, .md-body h4 {
  color: #1a73e8;
  margin: 16px 0 8px;
  font-weight: 600;
}
.md-body h1 { font-size: 20px; border-bottom: 2px solid #e8eaed; padding-bottom: 6px; }
.md-body h2 { font-size: 18px; }
.md-body h3 { font-size: 16px; }
.md-body p { margin: 8px 0; }
.md-body ul, .md-body ol { margin: 8px 0; padding-left: 24px; }
.md-body li { margin: 4px 0; line-height: 1.7; }
/* 表格样式 */
.md-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 13px;
}
.md-body th {
  background: #f8f9fa;
  padding: 8px 12px;
  font-weight: 600;
  border: 1px solid #dadce0;
  text-align: left;
  color: #5f6368;
  white-space: nowrap;
}
.md-body td {
  padding: 6px 12px;
  border: 1px solid #e8eaed;
}
.md-body tr:nth-child(even) {
  background: #fafbfc;
}
.md-body tr:hover {
  background: #f0f4ff;
}
.md-body code {
  background: #f1f3f4;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
  font-family: 'Consolas', 'Monaco', monospace;
}
.md-body pre {
  background: #f6f8fa;
  padding: 12px 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
  border: 1px solid #e8eaed;
}
.md-body pre code {
  background: none;
  padding: 0;
}
.md-body blockquote {
  border-left: 3px solid #1a73e8;
  padding: 8px 12px;
  color: #5f6368;
  margin: 8px 0;
  background: #f8f9fa;
  border-radius: 0 4px 4px 0;
}
.md-body strong { color: #202124; font-weight: 600; }
.md-body em { color: #5f6368; }
.md-body hr { border: none; border-top: 1px solid #e8eaed; margin: 16px 0; }
.md-body a { color: #1a73e8; text-decoration: none; }
.md-body a:hover { text-decoration: underline; }
.ai-anomaly-panel .action-bar {
  display: flex;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);
  flex-wrap: wrap;
}
</style>
