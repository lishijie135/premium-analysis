<template>
  <div>
    <div class="card" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px">
      <h2 class="card-title" style="margin: 0">分析结果</h2>
      <el-button type="warning" plain @click="emit('reupload')">重新上传</el-button>
    </div>

    <SummaryBar :summary="result.summary" />

    <div class="card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="业绩分析" name="dashboard">
          <DashboardPage :performance="result.performance" />
        </el-tab-pane>
        <el-tab-pane label="AI 异常分析" name="anomaly">
          <AiAnomalyPanel :session-id="sessionId" @session-expired="emit('session-expired')" />
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import SummaryBar from './SummaryBar.vue'
import DashboardPage from './DashboardPage.vue'
import AiAnomalyPanel from './AiAnomalyPanel.vue'

defineProps({
  result: { type: Object, required: true }, // /api/analyze 返回
  sessionId: { type: String, default: '' } // 上传会话 ID（AI 异常分析流式接口需要）
})
const emit = defineEmits(['reupload', 'session-expired'])

const activeTab = ref('dashboard')
</script>
