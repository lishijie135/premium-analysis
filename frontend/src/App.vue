<template>
  <div class="app-shell">
    <header class="app-header">
      <h1>客户业绩保费分析系统</h1>
      <el-tag v-if="mockMode" type="warning" effect="plain">Mock 预览模式</el-tag>
      <span class="muted">上传 Excel → 确认列映射 → 查看业绩统计与 AI 异常分析</span>
    </header>

    <el-steps :active="step" finish-status="success" align-center class="steps-bar">
      <el-step title="上传文件" />
      <el-step title="确认列映射" />
      <el-step title="分析结果" />
    </el-steps>

    <main>
      <UploadPage v-if="step === 0" @uploaded="onUploaded" />

      <MappingStep
        v-else-if="step === 1"
        :upload="uploadResult"
        :loading="analyzing"
        @back="step = 0"
        @confirm="onConfirmMapping"
      />

      <ResultPage
        v-else
        :result="result"
        :session-id="uploadResult ? uploadResult.session_id : ''"
        @reupload="reset"
        @session-expired="onSessionExpired"
      />
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import UploadPage from './components/UploadPage.vue'
import MappingStep from './components/MappingStep.vue'
import ResultPage from './components/ResultPage.vue'
import { analyze, isMockMode, SESSION_EXPIRED } from './api/client'

const mockMode = isMockMode()

const step = ref(0)
const uploadResult = ref(null) // /api/upload 返回：session_id/columns/preview_rows/auto_mapping/need_manual/warnings
const result = ref(null) // /api/analyze 返回：summary/performance/anomalies/growth
const analyzing = ref(false)

function onUploaded(res) {
  uploadResult.value = res
  step.value = 1
}

async function onConfirmMapping(mapping) {
  analyzing.value = true
  try {
    result.value = await analyze(uploadResult.value.session_id, mapping)
    step.value = 2
  } catch (err) {
    if (err.code === SESSION_EXPIRED) {
      ElMessage.error('会话已过期，请重新上传')
      reset()
    } else {
      ElMessage.error('分析失败：' + (err.response?.data?.detail || err.message || '未知错误'))
    }
  } finally {
    analyzing.value = false
  }
}

// AI 异常分析流式接口返回 404（会话过期）时的统一处理
function onSessionExpired() {
  ElMessage.error('会话已过期，请重新上传')
  reset()
}

function reset() {
  step.value = 0
  uploadResult.value = null
  result.value = null
}
</script>

<style scoped>
.steps-bar {
  margin: calc(var(--fs-base) * 1.25) 0 calc(var(--fs-base) * 1.5);
}
</style>
