<template>
  <div class="app-shell">
    <!-- 顶部 Header -->
    <header class="app-header">
      <div class="header-left">
        <div class="logo-icon">P</div>
        <h1>客户业绩保费分析系统</h1>
      </div>
      <div class="header-right">
        <span class="header-subtitle">Premium Analysis System</span>
        <el-tag v-if="mockMode" type="warning" effect="plain" size="small">Mock</el-tag>
      </div>
    </header>

    <!-- 步骤条 -->
    <div class="steps-container">
      <el-steps :active="step" finish-status="success" align-center class="steps-bar">
        <el-step title="上传文件" description="导入 Excel 数据" />
        <el-step title="确认列映射" description="校验字段对应关系" />
        <el-step title="分析结果" description="业绩统计与异常分析" />
      </el-steps>
    </div>

    <!-- 主内容区 -->
    <main class="app-main">
      <UploadPage v-if="step === 0" @uploaded="onUploaded" />

      <MappingStep
        v-else-if="step === 1"
        :upload="uploadResult"
        @back="step = 0"
        @confirm="onConfirmMapping"
      />

      <ResultPage
        v-else
        :session-id="uploadResult ? uploadResult.session_id : ''"
        :mapping="currentMapping"
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
import { isMockMode } from './api/client'

const mockMode = isMockMode()

const step = ref(0)
const uploadResult = ref(null)
const currentMapping = ref(null)

function onUploaded(res) {
  uploadResult.value = res
  step.value = 1
}

function onConfirmMapping(mapping) {
  // 保存 mapping 供后续使用
  currentMapping.value = mapping
  step.value = 2
}

function onSessionExpired() {
  ElMessage.error('会话已过期，请重新上传')
  reset()
}

function reset() {
  step.value = 0
  uploadResult.value = null
  currentMapping.value = null
}

</script>

<style scoped>
.steps-bar {
  max-width: 600px;
}
</style>
