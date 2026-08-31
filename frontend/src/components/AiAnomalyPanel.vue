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
      <!-- 当前分析范围提示（与业绩分析筛选联动） -->
      <div v-if="rangeText" class="range-bar">
        <el-icon><Calendar /></el-icon>
        <span>当前分析范围：<strong>{{ rangeText }}</strong></span>
        <span class="range-hint">（跟随业绩分析页的起止期筛选）</span>
      </div>

      <!-- 提示词模板管理区 -->
      <div class="prompt-box">
        <!-- 区域1：模板标签栏 -->
        <div class="template-tab-bar">
          <div class="template-tabs" role="tablist" aria-label="提示词模板">
            <div
              v-for="(t, idx) in templates" :key="t.id"
              class="template-tab"
              :class="{ active: !creatingTemplate && t.id === activeTemplateId }"
              :data-template-id="t.id"
              role="tab"
              :tabindex="!creatingTemplate && t.id === activeTemplateId ? 0 : -1"
              :aria-selected="!creatingTemplate && t.id === activeTemplateId ? 'true' : 'false'"
              @click="switchTemplate(t.id)"
              @dblclick.stop="startRenameTemplate(t)"
              @keydown="onTemplateKeydown($event, idx, t.id)"
              :title="t.name + '（双击重命名）'"
            >
              <!-- 重命名输入模式 -->
              <el-input
                v-if="renamingTemplateId === t.id"
                v-model="renamingName"
                size="small"
                style="width: 120px;"
                @click.stop
                @keyup.enter="confirmRenameTemplate"
                @keyup.escape="cancelRenameTemplate"
                @blur="confirmRenameTemplate"
                ref="renameInputRef"
              />
              <span v-else class="tab-name">{{ t.name }}</span>
              <span
                v-if="templates.length > 1 && renamingTemplateId !== t.id"
                class="tab-delete"
                @click.stop="handleDeleteTemplate(t.id)"
                title="删除模板"
              >&times;</span>
            </div>
            <!-- 新建模板按钮 -->
            <div class="template-tab template-tab-add" @click="showNewTemplateInput = true; creatingTemplate = true" title="新建模板">
              <span class="tab-add-icon">+</span>
            </div>
          </div>
        </div>

        <!-- 新建模板输入行 -->
        <div v-if="showNewTemplateInput" class="new-template-input-row">
          <el-input v-model="newTemplateName" placeholder="输入模板名称" size="small" style="width: 200px;" @keyup.enter="handleCreateTemplate" />
          <el-button type="success" size="small" @click="handleCreateTemplate" :loading="loadingPrompt">确认</el-button>
          <el-button size="small" @click="showNewTemplateInput = false; newTemplateName = ''; creatingTemplate = false">取消</el-button>
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
            <el-tooltip content="开启新会话" placement="top">
              <el-button size="small" :disabled="streaming" @click="refreshSession">
                <el-icon><Refresh /></el-icon>
                <span>新会话</span>
              </el-button>
            </el-tooltip>
            <el-button size="small" :disabled="!fullText || streaming" @click="copyMd">复制</el-button>
            <el-button size="small" :disabled="!fullText || streaming" @click="exportToPDF">导出 PDF</el-button>
          </div>
        </div>

        <!-- 错误提示（配置缺失 / 模型调用失败 / 会话过期等） -->
        <el-alert v-if="errorMsg" type="error" :closable="false" :title="errorMsg" class="err-alert" />

        <!-- Agent 执行过程面板（Code Interpreter 模式） -->
        <div v-if="showCodePanel || agentPhase" class="agent-process-panel">
          <div class="agent-phase-indicator">
            <el-icon v-if="agentPhase === 'generating' || agentPhase === 'executing'" class="is-loading"><Loading /></el-icon>
            <span class="agent-phase-text">
              {{ agentPhase === 'generating' ? '🤖 正在生成分析代码...' :
                 agentPhase === 'executing' ? '⚙️ 正在执行数据分析...' :
                 agentPhase === 'interpreting' ? '📝 正在撰写分析报告...' :
                 agentMessage || '准备中...' }}
            </span>
          </div>
          <!-- 可折叠的代码展示区 -->
          <el-collapse v-if="agentCode" v-model="codeCollapseActive">
            <el-collapse-item title="查看生成的分析代码" name="code">
              <pre class="agent-code-block"><code>{{ agentCode }}</code></pre>
            </el-collapse-item>
            <el-collapse-item v-if="execResult" title="查看执行结果" name="result">
              <pre class="agent-result-block"><code>{{ formatExecResult }}</code></pre>
            </el-collapse-item>
          </el-collapse>
        </div>

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
import { Loading, MagicStick, Refresh, Calendar } from '@element-plus/icons-vue'
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

/** 当前分析范围文案（来自业绩分析筛选） */
const rangeText = computed(() => {
  if (!props.startMonth && !props.endMonth) return ''
  return `${props.startMonth || '-'} ~ ${props.endMonth || '-'}`
})

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

// ---- Code Interpreter Agent 状态 ----
const agentCode = ref('') // 生成的 Python 代码
const agentPhase = ref('') // 当前阶段：'' | 'generating' | 'executing' | 'interpreting'
const execResult = ref('') // 代码执行结果 JSON
const agentMessage = ref('') // Agent 执行状态消息
const showCodePanel = ref(false) // 是否展示 Agent 执行过程面板
const codeCollapseActive = ref([]) // 折叠面板激活项

// 格式化执行结果 JSON
const formatExecResult = computed(() => {
  if (!execResult.value) return ''
  try {
    const obj = JSON.parse(execResult.value)
    return JSON.stringify(obj, null, 2)
  } catch {
    return execResult.value
  }
})

// ---- 多模板管理状态 ----
const templates = ref([]) // 模板列表 [{id, name, active}]
const activeTemplateId = ref('') // 当前激活的模板 ID
const editingTemplateId = ref('') // 正在编辑的模板 ID
const newTemplateName = ref('') // 新建模板名称
const showNewTemplateInput = ref(false) // 显示新建模板输入框
const creatingTemplate = ref(false) // 新建模板模式：期间取消所有模板选中高亮
const loadingTemplates = ref(false) // 模板列表加载中
const renamingTemplateId = ref('') // 正在重命名的模板 ID
const renamingName = ref('') // 重命名输入内容
const renameInputRef = ref(null) // 重命名输入框引用

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
  // 重置优化状态，确保按钮状态跟随当前模板正确联动
  optimizingPrompt.value = false
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
  creatingTemplate.value = false // 点击其他模板时退出新建模式
  try {
    await activateTemplate(templateId)
    activeTemplateId.value = templateId
    editingTemplateId.value = templateId
    await loadActiveTemplate()
  } catch (err) {
    ElMessage.error('切换模板失败：' + (err.message || '未知错误'))
  }
}

/** 键盘方向键在模板标签间移动焦点（跟随切换，交互流畅） */
function moveTemplateFocus(idx, step) {
  const next = (idx + step + templates.value.length) % templates.value.length
  const nextId = templates.value[next]?.id
  if (!nextId) return
  switchTemplate(nextId)
  const el = document.querySelector(`.template-tab[data-template-id="${nextId}"]`)
  el?.focus()
}

/**
 * 模板标签统一键盘处理：Enter/Space 激活、方向键移动焦点。
 * 重命名输入框处于激活状态时不响应（避免方向键/回车干扰输入）。
 */
function onTemplateKeydown(e, idx, id) {
  if (renamingTemplateId.value) return
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    switchTemplate(id)
  } else if (e.key === 'ArrowRight') {
    e.preventDefault()
    moveTemplateFocus(idx, 1)
  } else if (e.key === 'ArrowLeft') {
    e.preventDefault()
    moveTemplateFocus(idx, -1)
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
    const t = await createTemplate(newTemplateName.value.trim(), '')
    templates.value.push({ id: t.id, name: t.name, active: false })
    newTemplateName.value = ''
    showNewTemplateInput.value = false
    creatingTemplate.value = false
    ElMessage.success('模板已创建')
    // 创建成功后自动切换到新模板
    await switchTemplate(t.id)
  } catch (err) {
    ElMessage.error('创建模板失败：' + (err.message || '未知错误'))
  } finally {
    loadingPrompt.value = false
  }
}

/** 开始重命名模板 */
function startRenameTemplate(t) {
  renamingTemplateId.value = t.id
  renamingName.value = t.name
  nextTick(() => {
    // 自动聚焦输入框并全选文字
    const input = renameInputRef.value
    if (input && input.focus) input.focus()
  })
}

/** 确认重命名 */
async function confirmRenameTemplate() {
  const id = renamingTemplateId.value
  const newName = renamingName.value.trim()
  renamingTemplateId.value = ''
  if (!newName) {
    ElMessage.warning('模板名称不能为空')
    return
  }
  const t = templates.value.find(t => t.id === id)
  if (!t || t.name === newName) return // 名称未变化则跳过
  try {
    await updateTemplate(id, newName, t.content || '')
    t.name = newName
    ElMessage.success('模板已重命名')
  } catch (err) {
    ElMessage.error('重命名失败：' + (err.message || '未知错误'))
  }
}

/** 取消重命名 */
function cancelRenameTemplate() {
  renamingTemplateId.value = ''
  renamingName.value = ''
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

/** 流式输出时自动滚动到底部（跟随最近的可滚动祖先容器） */
function scrollOutputToBottom() {
  nextTick(() => {
    const el = document.querySelector('.ai-anomaly-panel .output-card')
    if (!el) return
    let node = el
    while (node) {
      if (node.scrollHeight > node.clientHeight && node !== document.body) {
        node.scrollTop = node.scrollHeight
        break
      }
      node = node.parentElement
    }
  })
}
watch(fullText, () => {
  if (streaming.value) scrollOutputToBottom()
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
  // 重置 Agent 状态
  agentCode.value = ''
  agentPhase.value = ''
  execResult.value = ''
  agentMessage.value = ''
  showCodePanel.value = false

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
    } else if (payload.type === 'code') {
      // Agent 阶段一：收到生成的代码
      agentCode.value = payload.content
      agentPhase.value = 'executing'
      showCodePanel.value = true
    } else if (payload.type === 'executing') {
      // Agent 执行状态更新
      agentMessage.value = payload.message
      if (!agentPhase.value || agentPhase.value === '') {
        agentPhase.value = 'generating'
      }
    } else if (payload.type === 'result') {
      // Agent 阶段一：收到代码执行结果
      execResult.value = payload.content
      agentPhase.value = 'interpreting'
    } else if (payload.type === 'warning') {
      ElMessage.warning(payload.message)
    } else if (payload.type === 'error') {
      errorMsg.value = payload.message || '分析失败'
    } else if (payload.type === 'done') {
      // 流正常结束（循环退出后 finally 会收尾）
    }
  }
}

/** 开启新会话：清空分析结果并重置状态 */
function refreshSession() {
  if (streaming.value) return
  // 中断可能存在的流式请求
  if (abortController) abortController.abort()
  fullText.value = ''
  errorMsg.value = ''
  streaming.value = false
  abortController = null
  // 重置 Agent 状态
  agentCode.value = ''
  agentPhase.value = ''
  execResult.value = ''
  agentMessage.value = ''
  showCodePanel.value = false
  ElMessage.success('已开始新会话')
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

import { exportMarkdownToPDF } from '../utils/pdf.js'

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

/** 导出分析结果为 PDF（jsPDF 生成真正 PDF 表格，文字可复制） */
async function exportToPDF() {
  if (!fullText.value || !fullText.value.trim()) {
    ElMessage.warning('暂无分析结果可导出')
    return
  }
  await exportMarkdownToPDF(fullText.value, 'AI 数据分析报告')
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

/* 分析范围提示条 */
.range-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: var(--fs-sm);
  color: var(--color-text-secondary);
  background: var(--bg-hover);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  margin-bottom: var(--spacing-md);
}
.range-bar .el-icon {
  color: var(--color-primary);
}
.range-bar .range-hint {
  color: var(--color-text-muted);
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
  background: #f5f5f7;
  color: #6e6e73;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
  max-width: 160px;
  user-select: none;
}
.template-tab:hover {
  background: #e8e8ed;
}
.template-tab:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
.template-tab.active {
  background: #0066cc;
  color: #fff;
  border-color: #0066cc;
  font-weight: 600;
}
.template-tab.active:hover {
  background: #0057b0;
}
.template-tab .tab-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 120px;
}
/* 重命名输入框在标签内的样式 */
.template-tab :deep(.el-input__wrapper) {
  padding: 0 6px;
  box-shadow: none;
  border: 1px solid #0066cc;
  border-radius: 3px;
  background: #fff;
}
.template-tab.active :deep(.el-input__wrapper) {
  border-color: #fff;
  background: rgba(255,255,255,0.9);
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
  color: #ff3b30;
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
  color: #6e6e73;
}
.editor-actions {
  display: flex;
  gap: 8px;
}
.editor-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #86868b;
}

/* ---- 操作按钮区域 ---- */
.template-tab-add {
  border-style: dashed;
  background: transparent;
  color: #86868b;
}
.template-tab-add:hover {
  border-color: #0066cc;
  color: #0066cc;
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
  color: #1d1d1f;
  word-break: break-word;
}
.md-body h1, .md-body h2, .md-body h3, .md-body h4 {
  color: #0066cc;
  margin: 16px 0 8px;
  font-weight: 600;
}
.md-body h1 { font-size: 20px; border-bottom: 2px solid #e8e8ed; padding-bottom: 6px; }
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
  background: #f5f5f7;
  padding: 8px 12px;
  font-weight: 600;
  border: 1px solid #d2d2d7;
  text-align: left;
  color: #6e6e73;
  white-space: nowrap;
}
.md-body td {
  padding: 6px 12px;
  border: 1px solid #e8e8ed;
}
.md-body tr:nth-child(even) {
  background: #fafafc;
}
.md-body tr:hover {
  background: #f0f6ff;
}
.md-body code {
  background: #f5f5f7;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
  font-family: 'Consolas', 'Monaco', monospace;
}
.md-body pre {
  background: #f5f5f7;
  padding: 12px 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
  border: 1px solid #e8e8ed;
}
.md-body pre code {
  background: none;
  padding: 0;
}
.md-body blockquote {
  border-left: 3px solid #0066cc;
  padding: 8px 12px;
  color: #6e6e73;
  margin: 8px 0;
  background: #f5f5f7;
  border-radius: 0 4px 4px 0;
}
.md-body strong { color: #1d1d1f; font-weight: 600; }
.md-body em { color: #6e6e73; }
.md-body hr { border: none; border-top: 1px solid #e8e8ed; margin: 16px 0; }
.md-body a { color: #0066cc; text-decoration: none; }
.md-body a:hover { text-decoration: underline; }
.ai-anomaly-panel .action-bar {
  display: flex;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);
  flex-wrap: wrap;
}

/* ---- Agent 执行过程面板 ---- */
.agent-process-panel {
  background: #f5f5f7;
  border: 1px solid #e8e8ed;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 16px;
}
.agent-phase-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.agent-phase-text {
  font-size: 14px;
  color: #6e6e73;
  font-weight: 500;
}
.agent-code-block,
.agent-result-block {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px 16px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  max-height: 300px;
  overflow-y: auto;
  margin: 0;
}
.agent-code-block code,
.agent-result-block code {
  background: none;
  padding: 0;
  color: inherit;
  font-size: inherit;
}
</style>
