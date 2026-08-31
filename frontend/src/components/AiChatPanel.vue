<template>
  <div class="ai-chat-panel">
    <!-- 当前分析范围提示（与业绩分析筛选联动） -->
    <div v-if="rangeText" class="chat-scope">
      <span class="scope-icon">
        <el-icon><Calendar /></el-icon>
      </span>
      <span class="scope-label">对话范围：</span>
      <strong class="scope-range">{{ rangeText }}</strong>
      <span class="scope-hint">（跟随业绩分析页的起止期筛选）</span>
      <span class="scope-meta">已分析 · {{ messages.length }} 条会话</span>
    </div>

    <!-- 消息列表区 -->
    <div class="chat-messages" ref="messagesContainer">
      <!-- 空状态提示 + 快捷问题 -->
      <div v-if="messages.length === 0" class="chat-empty">
        <span class="empty-badge"><span class="badge-dot"></span>AI Assistant · qwen3 本地推理</span>
        <p class="empty-title">基于已上传的数据，向我提问吧</p>
        <span class="empty-example"><span class="example-tag">例如</span>7 月份保费最高的客户有哪些？</span>
        <div class="quick-questions" role="group" aria-label="快捷问题">
          <button
            v-for="q in quickQuestions"
            :key="q"
            type="button"
            class="quick-question-chip"
            :disabled="streaming"
            @click="sendQuickQuestion(q)"
          >
            {{ q }}
          </button>
        </div>
      </div>
      <!-- 历史消息 -->
      <div
        v-for="(msg, index) in messages"
        :key="index"
        :class="['chat-message', msg.role === 'user' ? 'chat-user' : 'chat-assistant']"
      >
        <div class="message-avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
        <div class="message-content">
          <div v-if="msg.role === 'assistant'" class="md-body" v-html="msg.rendered"></div>
          <div v-else class="user-text">{{ msg.content }}</div>
          <!-- hover 操作按钮区（仅 AI 回复显示） -->
          <div v-if="msg.role === 'assistant'" class="message-actions">
            <el-tooltip content="复制" placement="top">
              <el-button
                size="small"
                text
                class="action-btn"
                @click="copySingleMessage(index)"
              >
                <el-icon><CopyDocument /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip content="导出 PDF" placement="top">
              <el-button
                size="small"
                text
                class="action-btn"
                @click="exportSingleToPDF(index)"
              >
                <el-icon><Printer /></el-icon>
              </el-button>
            </el-tooltip>
            <el-button
              size="small"
              text
              class="action-btn"
              title="重新发送该问题"
              :disabled="streaming"
              @click="resendMessage(index)"
            >
              <el-icon><RefreshRight /></el-icon>
              <span>重新发送</span>
            </el-button>
          </div>
        </div>
      </div>
      <!-- 流式输出指示器 -->
      <div v-if="streaming" class="chat-message chat-assistant">
        <div class="message-avatar">AI</div>
        <div class="message-content">
          <!-- Agent 执行过程面板（代码生成 / 执行中） -->
          <div v-if="chatAgentCode || chatAgentPhase" class="chat-agent-panel">
            <div class="chat-agent-phase">
              <el-icon v-if="chatAgentPhase === 'generating' || chatAgentPhase === 'executing'" class="is-loading"><Loading /></el-icon>
              <span>
                {{ chatAgentPhase === 'generating' ? '🤖 正在生成分析代码...' :
                   chatAgentPhase === 'executing' ? '⚙️ 正在执行数据分析...' :
                   chatAgentPhase === 'interpreting' ? '📝 正在撰写回答...' :
                   chatAgentMessage || '准备中...' }}
              </span>
            </div>
            <el-collapse v-if="chatAgentCode" v-model="chatCodeCollapse">
              <el-collapse-item title="查看分析代码" name="code">
                <pre class="chat-agent-code"><code>{{ chatAgentCode }}</code></pre>
              </el-collapse-item>
              <el-collapse-item v-if="chatExecResult" title="查看执行结果" name="result">
                <pre class="chat-agent-result"><code>{{ formatChatExecResult }}</code></pre>
              </el-collapse-item>
            </el-collapse>
          </div>
          <!-- Markdown 流式渲染 -->
          <div v-if="streamingContent" class="md-body" v-html="streamingContent"></div>
          <span v-if="streamingContent && chatAgentPhase === 'interpreting'" class="typing-cursor">|</span>
        </div>
      </div>
    </div>

    <!-- 底部输入区 -->
    <div class="chat-input-area">
      <div class="chat-footer">
        <span class="ready-dot"></span>
        <span class="ready-text">上下文已就绪，将基于上传的 Excel 数据作答</span>
        <span class="footer-right">
          <button
            type="button"
            class="clear-btn"
            @click="clearChat"
            :disabled="streaming || messages.length === 0"
          >清空对话</button>
          <span class="kbd-hint">⌘&nbsp;Enter 发送</span>
        </span>
      </div>
      <div class="chat-input-row">
        <el-tooltip content="开启新会话" placement="top">
          <button type="button" class="new-chat-btn" @click="refreshSession" :disabled="streaming">
            <span class="new-chat-plus">＋</span>
            <span>新会话</span>
          </button>
        </el-tooltip>
        <span class="row-divider"></span>
        <el-input
          ref="inputRef"
          v-model="inputMessage"
          placeholder="请输入你的问题..."
          @keyup.enter="sendMessage"
          @keydown.ctrl.enter.prevent="sendMessage"
          @keydown.meta.enter.prevent="sendMessage"
          :disabled="streaming"
          class="chat-input"
          :aria-label="'输入问题，按回车或 ⌘+Enter 发送'"
        />
        <button
          v-if="streaming"
          type="button"
          class="stop-btn"
          @click="stopStreaming"
        >
          <el-icon><VideoPause /></el-icon>
          <span>停止回答</span>
        </button>
        <button
          v-else
          type="button"
          class="send-btn"
          @click="sendMessage"
          :disabled="!inputMessage.trim()"
        >
          <span>发送</span>
          <span class="send-arrow">→</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * AiChatPanel.vue - AI 对话面板组件
 * 支持 SSE 流式输出、Markdown 渲染、对话清空
 * 新增功能：重新发送、复制结果、导出 PDF、单条消息复制/导出
 */
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { RefreshRight, CopyDocument, Printer, DocumentCopy, Download, VideoPause, Loading, Calendar } from '@element-plus/icons-vue'
import { marked } from 'marked'
import { clearChat as apiClearChat, isMockMode } from '../api/client.js'
import { exportMarkdownToPDF } from '../utils/pdf.js'

// marked 配置：GFM 表格 + 换行（与 AiAnomalyPanel 一致）
marked.setOptions({ gfm: true, breaks: true })

const props = defineProps({
  sessionId: { type: String, default: '' },   // 会话 ID
  startMonth: { type: String, default: '' },  // "YYYY-MM" 格式
  endMonth: { type: String, default: '' },    // "YYYY-MM" 格式
})

/** 对话范围文案（来自业绩分析筛选） */
const rangeText = computed(() => {
  if (!props.startMonth && !props.endMonth) return ''
  return `${props.startMonth || '-'} ~ ${props.endMonth || '-'}`
})

// ---- 响应式状态 ----
const messages = ref([])           // 对话消息列表
const inputMessage = ref('')       // 输入框内容
const streaming = ref(false)       // 是否正在流式输出
const streamingContent = ref('')   // 流式输出中的 HTML 内容
const messagesContainer = ref(null) // 消息列表容器 ref
const inputRef = ref(null)         // 输入框 ref（自动聚焦）
const abortController = ref(null)  // 用于中断流式请求（ref 以支持停止按钮）

/** 空状态下的快捷问题（直接作为用户消息发送） */
const quickQuestions = [
  '保费最高的月份有哪些？',
  '保费环比下降最多的客户是谁？',
  '本期内保费与出单量整体趋势如何？'
]

/** 快捷问题：直接发送 */
function sendQuickQuestion(q) {
  if (streaming.value || !q.trim()) return
  inputMessage.value = q
  sendMessage()
}

// 进入面板自动聚焦输入框，提升连续提问效率
onMounted(() => {
  nextTick(() => inputRef.value?.focus?.())
})

// ---- Code Interpreter Agent 状态 ----
const chatAgentCode = ref('')      // 当前轮次生成的代码
const chatAgentPhase = ref('')     // 当前阶段：'' | 'generating' | 'executing' | 'interpreting'
const chatExecResult = ref('')     // 当前轮次代码执行结果
const chatAgentMessage = ref('')   // Agent 执行状态消息
const chatCodeCollapse = ref([])   // 折叠面板激活项

// 格式化执行结果 JSON
const formatChatExecResult = computed(() => {
  if (!chatExecResult.value) return ''
  try {
    const obj = JSON.parse(chatExecResult.value)
    return JSON.stringify(obj, null, 2)
  } catch {
    return chatExecResult.value
  }
})

/** 滚动消息列表到底部 */
function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

/** 停止当前的流式输出，保留已生成的内容 */
function stopStreaming() {
  if (abortController.value) {
    abortController.value.abort()
    abortController.value = null
  }
  streaming.value = false
  streamingContent.value = ''
}

/**
 * 执行 SSE 流式请求的核心逻辑（供 sendMessage 和 resendMessage 复用）
 * @param {string} text - 用户问题文本
 */
async function doStreamRequest(text) {
  // ---- Mock 模式：模拟 SSE 流式响应，不发送真实请求 ----
  if (isMockMode()) {
    streaming.value = true
    streamingContent.value = ''
    console.log('[AiChatPanel] Mock 模式：模拟流式 AI 回复')

    const mockResponse = [
      '> ⚠️ **当前处于 Mock 模式**',
      '',
      '未连接真实后端，以下为模拟回复。如需接入真实 AI 对话，请设置环境变量 `VITE_USE_MOCK=false` 并配置后端 LLM 参数。',
      '',
      '---',
      '',
      '### 模拟分析结果',
      '',
      '| 指标 | 数值 |',
      '| --- | --- |',
      '| 总保费 | ¥ 1,234,567 |',
      '| 保单数 | 892 |',
      '| 环比增长 | +5.3% |',
      '',
      '以上数据仅为演示用途，不代表实际业务数据。',
    ].join('\n')

    // 模拟逐字流式输出效果
    const chars = mockResponse.split('')
    let accumulated = ''
    for (let i = 0; i < chars.length; i++) {
      accumulated += chars[i]
      streamingContent.value = marked.parse(accumulated)
      scrollToBottom()
      await new Promise(r => setTimeout(r, 15))
    }

    // 流结束后，将完整内容加入消息列表
    messages.value.push({
      role: 'assistant',
      content: mockResponse,
      rendered: marked.parse(mockResponse),
    })
    streamingContent.value = ''
    streaming.value = false
    scrollToBottom()
    return
  }

  // 开始流式输出
  streaming.value = true
  streamingContent.value = ''
  abortController.value = new AbortController()
  // 重置 Agent 状态
  chatAgentCode.value = ''
  chatAgentPhase.value = ''
  chatExecResult.value = ''
  chatAgentMessage.value = ''
  chatCodeCollapse.value = []

  let fullContent = '' // 累积的 Markdown 原文

  try {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: props.sessionId,
        message: text,
        start_month: props.startMonth,
        end_month: props.endMonth,
      }),
      signal: abortController.value.signal,
    })

    if (!res.ok) {
      throw new Error('HTTP ' + res.status)
    }

    // 使用 ReadableStream 逐块读取 SSE 数据
    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      // 按 SSE 事件分隔符切分（双换行）
      const parts = buffer.split('\n\n')
      buffer = parts.pop() // 末尾可能是不完整片段，留到下一轮

      for (const part of parts) {
        for (const line of part.split('\n')) {
          if (!line.startsWith('data:')) continue
          const data = line.slice(5).trim()
          if (!data || data === '[DONE]') continue

          try {
            const event = JSON.parse(data)
            if (event.type === 'delta') {
              // 增量追加 Markdown 内容
              fullContent += event.content
              streamingContent.value = marked.parse(fullContent)
              scrollToBottom()
            } else if (event.type === 'code') {
              // Agent 阶段一：收到生成的代码
              chatAgentCode.value = event.content
              chatAgentPhase.value = 'executing'
              scrollToBottom()
            } else if (event.type === 'executing') {
              // Agent 执行状态更新
              chatAgentMessage.value = event.message
              if (!chatAgentPhase.value) {
                chatAgentPhase.value = 'generating'
              }
              scrollToBottom()
            } else if (event.type === 'result') {
              // Agent 阶段一：收到代码执行结果
              chatExecResult.value = event.content
              chatAgentPhase.value = 'interpreting'
              scrollToBottom()
            } else if (event.type === 'error') {
              ElMessage.error(event.message || '分析出错')
            } else if (event.type === 'done') {
              // 流正常结束
            }
          } catch (e) {
            // 跳过无法解析的行
            console.warn('[AiChatPanel] SSE 解析失败:', e)
          }
        }
      }
    }

    // 流结束后，将完整内容加入消息列表
    messages.value.push({
      role: 'assistant',
      content: fullContent,
      rendered: marked.parse(fullContent),
    })
    streamingContent.value = ''
    // 流结束后重置 Agent 阶段
    chatAgentPhase.value = ''
  } catch (err) {
    if (err.name === 'AbortError') {
      // 手动停止，将已生成内容保存
      if (fullContent) {
        messages.value.push({
          role: 'assistant',
          content: fullContent,
          rendered: marked.parse(fullContent),
        })
      }
    } else {
      ElMessage.error('请求失败：' + err.message)
    }
  } finally {
    streaming.value = false
    abortController.value = null
    chatAgentPhase.value = ''
    scrollToBottom()
  }
}

/**
 * 发送用户消息并发起 SSE 流式请求
 * SSE 事件格式：{type: "delta", content: "..."} / {type: "error", message: "..."} / {type: "done"}
 */
async function sendMessage() {
  const text = inputMessage.value.trim()
  if (!text || streaming.value) return

  // 清空输入框，添加用户消息
  inputMessage.value = ''
  messages.value.push({ role: 'user', content: text })
  scrollToBottom()

  // 调用核心流式请求逻辑
  await doStreamRequest(text)
}

/**
 * 重新发送：删除当前 AI 回复及之后的所有消息，重新发送对应的用户问题
 * @param {number} aiIndex - AI 回复消息在 messages 数组中的索引
 */
async function resendMessage(aiIndex) {
  if (streaming.value) return

  // 向前查找对应的用户消息
  let userIndex = -1
  for (let i = aiIndex - 1; i >= 0; i--) {
    if (messages.value[i].role === 'user') {
      userIndex = i
      break
    }
  }
  if (userIndex === -1) {
    ElMessage.warning('未找到对应的用户问题')
    return
  }

  // 获取用户问题文本
  const userText = messages.value[userIndex].content

  // 截取消息数组到用户问题位置（删除该 AI 回复及之后的所有消息）
  messages.value = messages.value.slice(0, userIndex + 1)
  scrollToBottom()

  console.log(`[AiChatPanel] 重新发送问题: ${userText}`)

  // 重新调用流式请求逻辑
  await doStreamRequest(userText)
}

/**
 * 复制单条 AI 回复内容到剪贴板
 * @param {number} index - 消息在 messages 数组中的索引
 */
async function copySingleMessage(index) {
  const msg = messages.value[index]
  if (!msg) return
  const text = msg.content
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    // 降级方案：非 HTTPS 或权限受限时用 execCommand
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    ElMessage.success('已复制到剪贴板')
  }
}

/**
 * 导出单条 AI 回复为 PDF（jsPDF 生成真正 PDF 表格，文字可复制）
 * @param {number} index - 消息在 messages 数组中的索引
 */
async function exportSingleToPDF(index) {
  const msg = messages.value[index]
  if (!msg || !msg.content) {
    ElMessage.warning('暂无内容可导出')
    return
  }
  await exportMarkdownToPDF(msg.content, 'AI 回复')
}



/** HTML 特殊字符转义 */
function escapeHtml(text) {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}

/** 开启新会话：清空对话记录并重置所有状态 */
async function refreshSession() {
  if (streaming.value) return
  try {
    if (!isMockMode()) {
      await apiClearChat(props.sessionId)
    }
    messages.value = []
    streamingContent.value = ''
    inputMessage.value = ''
    ElMessage.success('已开始新会话')
  } catch (err) {
    ElMessage.error('重置失败：' + (err.message || '未知错误'))
  }
}

/** 清空对话记录（Mock 模式直接清空，非 Mock 模式调用后端接口） */
async function clearChat() {
  try {
    if (isMockMode()) {
      // Mock 模式：仅清空本地消息列表，无需调用后端
      messages.value = []
      console.log('[AiChatPanel] Mock 模式：本地清空对话历史')
      ElMessage.success('对话已清空')
      return
    }
    await apiClearChat(props.sessionId)
    messages.value = []
    ElMessage.success('对话已清空')
  } catch (err) {
    ElMessage.error('清空失败：' + (err.message || '未知错误'))
  }
}

// 组件卸载时中断未完成的流式请求
onBeforeUnmount(() => {
  if (abortController.value) abortController.value.abort()
})
</script>

<style scoped>
/* ========================================
   AI 对话面板 — Apple Design 风格重制
   配色：Action Blue #0066cc / Ink #1d1d1f / Parchment #f5f5f7
   ======================================== */

/* 外层容器（ResultPage 的卡片）已提供边框与圆角，此处保持透明 */
.ai-chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: transparent;
  overflow: hidden;
  font-family: var(--font-family);
}

/* ---- 对话范围提示条 ---- */
.chat-scope {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
  font-size: 13px;
  color: #7a7a7a;
  background: #f5f5f7;
  border-radius: 12px;
  margin: 16px 16px 0;
  padding: 12px 18px;
}
.scope-icon {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.scope-icon .el-icon {
  color: #0066cc;
}
.scope-range {
  color: #1d1d1f;
  font-weight: 600;
  font-size: 14px;
  letter-spacing: -0.224px;
}
.scope-hint {
  color: #a1a1a6;
}
.scope-meta {
  margin-left: auto;
  color: #a1a1a6;
  font-size: 12px;
}

/* ---- 消息列表区：占据剩余高度，可滚动 ---- */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

/* ---- 空状态提示 ---- */
.chat-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 14px;
  color: #7a7a7a;
}
.empty-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid #e0e0e0;
  background: #ffffff;
  font-size: 12px;
  font-weight: 500;
  color: #7a7a7a;
  letter-spacing: -0.12px;
}
.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #0066cc;
}
.empty-title {
  font-size: 34px;
  font-weight: 600;
  color: #1d1d1f;
  letter-spacing: -0.374px;
  margin: 0;
  text-align: center;
}
.empty-example {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: #fafafc;
  border: 1px solid #f0f0f0;
  padding: 10px 18px;
  border-radius: 999px;
  font-size: 14px;
  color: #1d1d1f;
  letter-spacing: -0.224px;
}
.example-tag {
  font-size: 13px;
  color: #7a7a7a;
  font-weight: 500;
}

/* ---- 快捷问题 ---- */
.quick-questions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  justify-content: center;
  margin-top: 10px;
}
.quick-question-chip {
  display: inline-flex;
  align-items: center;
  border: 1px solid #e0e0e0;
  background: #ffffff;
  color: #1d1d1f;
  font-size: 14px;
  letter-spacing: -0.224px;
  padding: 11px 18px;
  border-radius: 999px;
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease,
    background-color 0.2s ease;
}
.quick-question-chip:hover:not(:disabled) {
  border-color: #0066cc;
  box-shadow: 0 0 0 3px rgba(0, 102, 204, 0.1);
}
.quick-question-chip:active:not(:disabled) {
  transform: scale(0.96);
}
.quick-question-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.quick-question-chip:focus-visible {
  outline: 2px solid #0066cc;
  outline-offset: 2px;
}

/* ---- 单条消息 ---- */
.chat-message {
  display: flex;
  gap: 12px;
  margin-bottom: 14px;
  align-items: flex-start;
  animation: message-in 0.22s ease;
}
@keyframes message-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .chat-message {
    animation: none;
  }
}

/* 用户消息：右对齐，Ink 黑底白字 */
.chat-message.chat-user {
  flex-direction: row-reverse;
}
.chat-message.chat-user .message-content {
  align-items: flex-end;
}
.chat-message.chat-user .user-text {
  background: #1d1d1f;
  color: #ffffff;
  border-radius: 12px 3px 12px 12px;
  padding: 12px 16px;
  max-width: 85%;
  word-break: break-word;
  line-height: 1.6;
}

/* AI 消息：左对齐，Surface 底 Hairline 边 */
.chat-message.chat-assistant .message-content .md-body {
  background: #fafafc;
  border-radius: 3px 12px 12px 12px;
  border: 1px solid #f0f0f0;
  padding: 12px 16px;
  max-width: 85%;
}

/* ---- 头像 ---- */
.message-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}
.chat-user .message-avatar {
  background: #1d1d1f;
  color: #fff;
}
.chat-assistant .message-avatar {
  background: #0066cc;
  color: #fff;
}

/* ---- 消息操作按钮：默认隐藏，hover 时显示 ---- */
.message-actions {
  display: flex;
  gap: 4px;
  margin-top: 4px;
  opacity: 0;
  transition: opacity 0.2s ease;
}
.chat-message:hover .message-actions {
  opacity: 1;
}
.message-actions .action-btn {
  font-size: 12px;
  color: #7a7a7a;
  padding: 2px 6px;
}
.message-actions .action-btn:hover {
  color: #0066cc;
}
.message-actions .action-btn .el-icon {
  margin-right: 2px;
}

/* ---- 打字光标动画 ---- */
.typing-cursor {
  display: inline-block;
  animation: blink 1s step-end infinite;
  color: #0066cc;
  font-weight: 700;
  margin-left: 2px;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* ---- 底部输入区 ---- */
.chat-input-area {
  flex-shrink: 0;
  padding: 0 16px 16px;
  background: #ffffff;
}

/* 状态提示行 */
.chat-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 10px 8px;
}
.ready-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #34c759;
  flex-shrink: 0;
}
.ready-text {
  font-size: 12px;
  color: #7a7a7a;
  letter-spacing: -0.12px;
}
.footer-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
}
.clear-btn {
  border: none;
  background: none;
  font-size: 12px;
  color: #7a7a7a;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  font-family: inherit;
  letter-spacing: -0.12px;
  transition: color 0.2s ease, background-color 0.2s ease;
}
.clear-btn:hover:not(:disabled) {
  color: #0066cc;
  background: #f5f5f7;
}
.clear-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.kbd-hint {
  font-size: 12px;
  color: #a1a1a6;
  letter-spacing: -0.12px;
}

/* 输入行：整体一个 pill 容器 */
.chat-input-row {
  display: flex;
  align-items: center;
  gap: 14px;
  background: #fafafc;
  border: 1px solid #e0e0e0;
  border-radius: 999px;
  padding: 10px 12px 10px 14px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.chat-input-row:focus-within {
  border-color: #0066cc;
  box-shadow: 0 0 0 3px rgba(0, 102, 204, 0.12);
}
.row-divider {
  width: 1px;
  height: 24px;
  background: #e0e0e0;
  flex-shrink: 0;
}

/* 新会话按钮 */
.new-chat-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #ffffff;
  border: 1px solid #e0e0e0;
  color: #1d1d1f;
  padding: 8px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  flex-shrink: 0;
  transition: border-color 0.2s ease, color 0.2s ease, background-color 0.2s ease;
}
.new-chat-btn:hover:not(:disabled) {
  border-color: #0066cc;
  color: #0066cc;
}
.new-chat-btn:active:not(:disabled) {
  transform: scale(0.96);
}
.new-chat-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.new-chat-plus {
  color: #0066cc;
  font-size: 13px;
  font-weight: 600;
}

/* 输入框：透明融入 pill 容器 */
.chat-input {
  flex: 1;
}
.chat-input :deep(.el-input__wrapper) {
  background: transparent;
  box-shadow: none;
  padding: 4px 6px;
}
.chat-input :deep(.el-input__inner) {
  font-size: 17px;
  color: #1d1d1f;
  font-family: inherit;
  letter-spacing: -0.374px;
}
.chat-input :deep(.el-input__inner)::placeholder {
  color: #a1a1a6;
}
.chat-input :deep(.el-input__wrapper.is-disabled) {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 发送按钮 */
.send-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  border: none;
  cursor: pointer;
  background: #0066cc;
  color: #ffffff;
  padding: 12px 22px;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.224px;
  font-family: inherit;
  flex-shrink: 0;
  transition: background-color 0.2s ease, transform 0.2s ease, opacity 0.2s ease;
}
.send-btn:hover:not(:disabled) {
  background: #0071e3;
}
.send-btn:active:not(:disabled) {
  transform: scale(0.96);
}
.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.send-arrow {
  font-size: 16px;
  line-height: 1;
}

/* 停止回答按钮 */
.stop-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  border: none;
  cursor: pointer;
  background: #ff3b30;
  color: #ffffff;
  padding: 12px 18px;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.224px;
  font-family: inherit;
  flex-shrink: 0;
  transition: background-color 0.2s ease, transform 0.2s ease;
}
.stop-btn:hover {
  background: #ff5147;
}
.stop-btn:active {
  transform: scale(0.96);
}

/* ---- Markdown 内容样式（Apple 风格） ---- */
.md-body {
  font-size: 14px;
  line-height: 1.8;
  color: #1d1d1f;
  word-break: break-word;
}
.md-body h1, .md-body h2, .md-body h3, .md-body h4 {
  color: #1d1d1f;
  margin: 16px 0 8px;
  font-weight: 600;
  letter-spacing: -0.374px;
}
.md-body h1 { font-size: 20px; border-bottom: 1px solid #f0f0f0; padding-bottom: 6px; }
.md-body h2 { font-size: 18px; }
.md-body h3 { font-size: 16px; }
.md-body p { margin: 8px 0; }
.md-body ul, .md-body ol { margin: 8px 0; padding-left: 24px; }
.md-body li { margin: 4px 0; line-height: 1.7; }
.md-body table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; }
.md-body th { background: #f5f5f7; padding: 8px 12px; font-weight: 600; border: 1px solid #e8eaed; text-align: left; color: #7a7a7a; white-space: nowrap; }
.md-body td { padding: 6px 12px; border: 1px solid #f0f0f0; }
.md-body tr:nth-child(even) { background: #fafbfc; }
.md-body tr:hover { background: #f0f6ff; }
.md-body code { background: #f5f5f7; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-family: 'SF Mono', 'Consolas', 'Monaco', monospace; }
.md-body pre { background: #f5f5f7; padding: 12px 16px; border-radius: 8px; overflow-x: auto; margin: 8px 0; border: 1px solid #f0f0f0; }
.md-body pre code { background: none; padding: 0; }
.md-body blockquote { border-left: 3px solid #0066cc; padding: 8px 12px; color: #7a7a7a; margin: 8px 0; background: #f5f5f7; border-radius: 0 4px 4px 0; }
.md-body strong { color: #1d1d1f; font-weight: 600; }
.md-body em { color: #7a7a7a; }
.md-body hr { border: none; border-top: 1px solid #f0f0f0; margin: 16px 0; }
.md-body a { color: #0066cc; text-decoration: none; }
.md-body a:hover { text-decoration: underline; }

/* ---- Chat Agent 执行过程面板 ---- */
.chat-agent-panel {
  background: #f5f5f7;
  border: 1px solid #f0f0f0;
  border-radius: 12px;
  padding: 10px 14px;
  margin-bottom: 10px;
}
.chat-agent-phase {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 13px;
  color: #7a7a7a;
  font-weight: 500;
}
.chat-agent-code,
.chat-agent-result {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 10px 14px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  max-height: 250px;
  overflow-y: auto;
  margin: 0;
}
.chat-agent-code code,
.chat-agent-result code {
  background: none;
  padding: 0;
  color: inherit;
  font-size: inherit;
}
</style>
