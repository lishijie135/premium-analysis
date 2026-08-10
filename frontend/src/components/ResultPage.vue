<template>
  <div class="result-page">
    <div class="card" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px">
      <h2 class="card-title" style="margin: 0">分析结果</h2>
      <el-button type="warning" plain @click="emit('reupload')">重新上传</el-button>
    </div>

    <div class="card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="业绩分析" name="dashboard">
          <DashboardPage :session-id="sessionId" :mapping="mapping" @range-change="onRangeChange" @session-expired="$emit('session-expired')" />
        </el-tab-pane>
        <el-tab-pane label="异常客户分析" name="anomaly-rules">
          <RuleAnomalyPanel
            :session-id="sessionId"
            :start-month="range.start"
            :end-month="range.end"
          />
        </el-tab-pane>
        <el-tab-pane label="AI 数据分析" name="anomaly">
          <AiAnomalyPanel :session-id="sessionId" :start-month="range.start" :end-month="range.end" @session-expired="emit('session-expired')" />
        </el-tab-pane>
        <el-tab-pane label="AI 智能对话" name="chat">
          <AiChatPanel :session-id="sessionId" :start-month="range.start" :end-month="range.end" />
        </el-tab-pane>

      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
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

// 维护 DashboardPage 的时间范围，传递给 AiAnomalyPanel
const range = ref({ start: '', end: '' })
function onRangeChange({ start, end }) {
  range.value = { start, end }
}
</script>

<style scoped>
.result-page {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.result-page .page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-md);
}
.result-page .page-title {
  font-size: var(--fs-xl);
  font-weight: 600;
  color: var(--color-text-primary);
}
.result-page .el-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.result-page .el-tabs__header {
  margin-bottom: 0;
  background: var(--bg-card);
  padding: 0 var(--spacing-md);
  border-radius: var(--radius-md) var(--radius-md) 0 0;
  border-bottom: 1px solid var(--color-border-light);
}
.result-page .el-tabs__content {
  flex: 1;
  overflow: auto;
  padding: var(--spacing-md);
  background: var(--bg-card);
  border-radius: 0 0 var(--radius-md) var(--radius-md);
}
</style>
