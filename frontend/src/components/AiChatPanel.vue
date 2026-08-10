<template>
  <div class="ai-chat-panel">
    <!-- 消息列表区 -->
    <div class="chat-messages" ref="messagesContainer">
      <!-- 空状态提示 -->
      <div v-if="messages.length === 0" class="chat-empty">
        <p>基于上传的数据，向我提问吧</p>
        <p class="chat-hint">例如：7月份保费最高的客户有哪些？</p>
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
          <div class="md-body" v-html="streamingContent"></div>
          <span class="typing-cursor">|</span>
        </div>
      </div>
    </div>

    <!-- 底部输入区 -->
    <div class="chat-input-area">
      <el-button size="small" @click="clearChat" :disabled="streaming || messages.length === 0">清空对话</el-button>
      <el-input
        v-model="inputMessage"
        placeholder="输入你的问题..."
        @keyup.enter="sendMessage"
        :disabled="streaming"
        class="chat-input"
      />
      <el-button v-if="streaming" type="danger" size="small" @click="stopStreaming">
        <el-icon><VideoPause /></el-icon>
        <span>停止回答</span>
      </el-button>
      <el-button v-else type="primary" @click="sendMessage" :disabled="!inputMessage.trim()">发送</el-button>
    </div>
  </div>
</template>

<script setup>
/**
 * AiChatPanel.vue - AI 对话面板组件
 * 支持 SSE 流式输出、Markdown 渲染、对话清空
 * 新增功能：重新发送、复制结果、导出 PDF、单条消息复制/导出
 */
import { ref, nextTick, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { RefreshRight, CopyDocument, Printer, DocumentCopy, Download, VideoPause } from '@element-plus/icons-vue'
import { marked } from 'marked'
import { clearChat as apiClearChat, isMockMode } from '../api/client.js'

// marked 配置：GFM 表格 + 换行（与 AiAnomalyPanel 一致）
marked.setOptions({ gfm: true, breaks: true })

const props = defineProps({
  sessionId: { type: String, default: '' },   // 会话 ID
  startMonth: { type: String, default: '' },  // "YYYY-MM" 格式
  endMonth: { type: String, default: '' },    // "YYYY-MM" 格式
})

// ---- 响应式状态 ----
const messages = ref([])           // 对话消息列表
const inputMessage = ref('')       // 输入框内容
const streaming = ref(false)       // 是否正在流式输出
const streamingContent = ref('')   // 流式输出中的 HTML 内容
const messagesContainer = ref(null) // 消息列表容器 ref
const abortController = ref(null)  // 用于中断流式请求（ref 以支持停止按钮）

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
 * 导出单条 AI 回复为 PDF（通过打印对话框另存）
 * @param {number} index - 消息在 messages 数组中的索引
 */
function exportSingleToPDF(index) {
  const msg = messages.value[index]
  if (!msg) return
  const htmlContent = marked.parse(msg.content || '')
  const printWindow = window.open('', '_blank')
  if (!printWindow) {
    ElMessage.warning('请允许弹出窗口以导出 PDF')
    return
  }
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>AI 回复</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 20px; color: #333; }
.ai-content { background: #f5f7fa; border-radius: 8px; padding: 16px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; }
th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
th { background: #f0f0f0; }
code { background: #f0f0f0; padding: 2px 4px; border-radius: 3px; }
pre { background: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; }
</style></head><body>
<h3>AI 回复</h3>
<div class="ai-content">${htmlContent}</div>
</body></html>`
  printWindow.document.write(html)
  printWindow.document.close()
  printWindow.focus()
  setTimeout(() => printWindow.print(), 300)
}



/** HTML 特殊字符转义 */
function escapeHtml(text) {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
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
/* ---- 面板容器：flex 纵向布局，高度自适应父容器 ---- */
.ai-chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  font-size: var(--fs-base);
  background: var(--bg-card);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
  overflow: hidden;
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
  color: var(--color-text-muted);
  font-size: var(--fs-base);
  gap: var(--spacing-xs);
}
.chat-empty .chat-hint {
  font-size: var(--fs-sm);
  color: var(--color-text-muted);
  background: var(--bg-hover);
  padding: var(--spacing-xs) var(--spacing-md);
  border-radius: var(--radius-sm);
}

/* ---- 单条消息 ---- */
.chat-message {
  display: flex;
  gap: var(--spacing-sm);
  margin-bottom: 12px;
  align-items: flex-start;
}

/* 用户消息：右对齐 */
.chat-message.chat-user {
  flex-direction: row-reverse;
}
.chat-message.chat-user .message-content {
  align-items: flex-end;
}
.chat-message.chat-user .user-text {
  background: #e8f0fe;
  color: var(--color-text-primary);
  border-radius: 12px 4px 12px 12px;
  padding: 12px 16px;
  max-width: 85%;
  word-break: break-word;
  line-height: 1.6;
}

/* AI 消息：左对齐 */
.chat-message.chat-assistant .message-content .md-body {
  background: #f8f9fa;
  border-radius: 4px 12px 12px 12px;
  border: 1px solid #e8eaed;
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
  font-size: var(--fs-sm);
  font-weight: 600;
  flex-shrink: 0;
}
.chat-user .message-avatar {
  background: var(--color-primary);
  color: #fff;
}
.chat-assistant .message-avatar {
  background: var(--color-success);
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
  color: var(--color-text-muted);
  padding: 2px 6px;
}
.message-actions .action-btn:hover {
  color: var(--color-primary);
}
.message-actions .action-btn .el-icon {
  margin-right: 2px;
}

/* ---- 打字光标动画 ---- */
.typing-cursor {
  display: inline-block;
  animation: blink 1s step-end infinite;
  color: var(--color-primary);
  font-weight: 700;
  margin-left: 2px;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* ---- 底部输入区：固定在底部 ---- */
.chat-input-area {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  padding: 12px 16px;
  border-top: 1px solid #e8eaed;
  background: var(--bg-card);
  flex-shrink: 0;
}
.chat-input-area .chat-input {
  flex: 1;
}

/* ---- Markdown 内容样式（增强版） ---- */
.md-body {
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
.md-body table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; }
.md-body th { background: #f8f9fa; padding: 8px 12px; font-weight: 600; border: 1px solid #dadce0; text-align: left; color: #5f6368; white-space: nowrap; }
.md-body td { padding: 6px 12px; border: 1px solid #e8eaed; }
.md-body tr:nth-child(even) { background: #fafbfc; }
.md-body tr:hover { background: #f0f4ff; }
.md-body code { background: #f1f3f4; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-family: 'Consolas', 'Monaco', monospace; }
.md-body pre { background: #f6f8fa; padding: 12px 16px; border-radius: 8px; overflow-x: auto; margin: 8px 0; border: 1px solid #e8eaed; }
.md-body pre code { background: none; padding: 0; }
.md-body blockquote { border-left: 3px solid #1a73e8; padding: 8px 12px; color: #5f6368; margin: 8px 0; background: #f8f9fa; border-radius: 0 4px 4px 0; }
.md-body strong { color: #202124; font-weight: 600; }
.md-body em { color: #5f6368; }
.md-body hr { border: none; border-top: 1px solid #e8eaed; margin: 16px 0; }
.md-body a { color: #1a73e8; text-decoration: none; }
.md-body a:hover { text-decoration: underline; }
</style>
