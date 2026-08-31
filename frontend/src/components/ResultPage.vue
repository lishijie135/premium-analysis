<template>
  <div class="result-page">
    <!-- 顶部导航：标题 + 操作 -->
    <div class="result-subnav">
      <div class="subnav-title">
        <h2>分析结果</h2>
        <span class="subnav-sub">{{ rangeText }}</span>
      </div>
      <button type="button" class="btn-primary" @click="emit('reupload')">重新上传</button>
    </div>

    <!-- 横向 pill Tab 行 -->
    <div class="tab-bar" role="tablist" aria-label="分析视图">
      <button
        v-for="t in tabs"
        :key="t.name"
        type="button"
        role="tab"
        class="tab-chip"
        :class="{ 'is-active': activeTab === t.name }"
        :aria-selected="activeTab === t.name"
        @click="activeTab = t.name"
      >
        <span>{{ t.label }}</span>
        <kbd class="tab-kbd">{{ t.kbd }}</kbd>
      </button>
    </div>

    <!-- 内容区 -->
    <div class="result-content">
      <div v-if="visited.has('dashboard')" v-show="isActive('dashboard')" class="pane-wrap">
        <DashboardPage :session-id="sessionId" :mapping="mapping" @range-change="onRangeChange" @session-expired="$emit('session-expired')" />
      </div>
      <div v-if="visited.has('anomaly-rules')" v-show="isActive('anomaly-rules')" class="pane-wrap">
        <RuleAnomalyPanel
          :session-id="sessionId"
          :start-month="range.start"
          :end-month="range.end"
        />
      </div>
      <div v-if="visited.has('anomaly')" v-show="isActive('anomaly')" class="pane-wrap">
        <AiAnomalyPanel :session-id="sessionId" :start-month="range.start" :end-month="range.end" @session-expired="emit('session-expired')" />
      </div>
      <div v-if="visited.has('chat')" v-show="isActive('chat')" class="pane-wrap is-flush">
        <AiChatPanel :session-id="sessionId" :start-month="range.start" :end-month="range.end" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import DashboardPage from './DashboardPage.vue'
import AiAnomalyPanel from './AiAnomalyPanel.vue'
import AiChatPanel from './AiChatPanel.vue'
import RuleAnomalyPanel from './RuleAnomalyPanel.vue'

defineProps({
  sessionId: { type: String, default: '' }, // 上传会话 ID
  mapping: { type: Object, default: () => ({}) } // 用户确认的列映射
})
const emit = defineEmits(['reupload', 'session-expired'])

const activeTab = ref('dashboard')

/** Tab 定义（顺序与快捷键一一对应） */
const tabs = [
  { name: 'dashboard', label: '业绩分析', kbd: '⌘1' },
  { name: 'anomaly-rules', label: '异常客户分析', kbd: '⌘2' },
  { name: 'anomaly', label: 'AI 数据分析', kbd: '⌘3' },
  { name: 'chat', label: 'AI 智能对话', kbd: '⌘4' }
]

// 懒加载：访问过的 Tab 才创建，之后用 v-show 保持状态
const visited = ref(new Set(['dashboard']))
watch(activeTab, (v) => visited.value.add(v))
const isActive = (name) => activeTab.value === name

// 维护 DashboardPage 的时间范围，传递给 AiAnomalyPanel
const range = ref({ start: '', end: '' })
function onRangeChange({ start, end }) {
  range.value = { start, end }
}

const rangeText = computed(() => {
  if (!range.value.start && !range.value.end) return '未选择时间范围'
  return `${range.value.start} ~ ${range.value.end}`
})

// Tab 快捷键：Ctrl/⌘ + 1~4 快速切换
function onGlobalKeydown(e) {
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey) {
    const idx = Number(e.key)
    if (idx >= 1 && idx <= tabs.length) {
      e.preventDefault()
      activeTab.value = tabs[idx - 1].name
    }
  }
}
onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKeydown))
</script>

<style scoped>
.result-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ---- 顶部导航 ---- */
.result-subnav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  flex-shrink: 0;
  padding: 0 4px;
}
.subnav-title {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}
.subnav-title h2 {
  font-size: 28px;
  font-weight: 600;
  letter-spacing: -0.374px;
  color: var(--color-text-primary);
  margin: 0;
}
.subnav-sub {
  font-size: 13px;
  color: var(--color-text-muted);
  letter-spacing: -0.1px;
}
.btn-primary {
  border: none;
  cursor: pointer;
  background: var(--color-primary);
  color: #ffffff;
  padding: 9px 22px;
  border-radius: var(--radius-pill);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.224px;
  font-family: inherit;
  transition: background-color 0.2s ease, transform 0.2s ease;
}
.btn-primary:hover {
  background: var(--color-primary-hover);
}
.btn-primary:active {
  transform: scale(0.96);
}

/* ---- 横向 pill Tab ---- */
.tab-bar {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  flex-wrap: wrap;
}
.tab-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--color-border-light);
  background: var(--bg-card);
  color: var(--color-text-muted);
  padding: 8px 16px;
  border-radius: var(--radius-pill);
  font-size: 14px;
  letter-spacing: -0.224px;
  cursor: pointer;
  font-family: inherit;
  transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease,
    transform 0.2s ease;
}
.tab-chip:hover:not(.is-active) {
  border-color: var(--color-border);
  color: var(--color-text-primary);
}
.tab-chip:active {
  transform: scale(0.97);
}
.tab-chip.is-active {
  background: #1d1d1f;
  border-color: #1d1d1f;
  color: #ffffff;
  font-weight: 600;
}
.tab-chip:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
.tab-kbd {
  font-size: 11px;
  line-height: 1;
  color: #a1a1a6;
  background: var(--bg-page);
  border-radius: 4px;
  padding: 3px 5px;
  font-family: inherit;
  transition: color 0.2s ease, background-color 0.2s ease;
}
.tab-chip.is-active .tab-kbd {
  background: rgba(255, 255, 255, 0.15);
  color: #d2d2d7;
}

/* ---- 内容区 ---- */
.result-content {
  flex: 1;
  min-height: 0;
  background: var(--bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.pane-wrap {
  height: 100%;
  padding: var(--spacing-lg);
  overflow-y: auto;
  animation: pane-in 0.25s ease;
}
/* Chat 面板自带内边距，容器内不再重复 */
.pane-wrap.is-flush {
  padding: 0;
  overflow: hidden;
}

@keyframes pane-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .pane-wrap {
    animation: none;
  }
}

/* 移动端：Tab 行可横向滚动 */
@media (max-width: 768px) {
  .subnav-title h2 {
    font-size: 21px;
  }
  .tab-bar {
    flex-wrap: nowrap;
    overflow-x: auto;
    padding-bottom: 4px;
  }
  .tab-chip {
    flex-shrink: 0;
  }
}
</style>
