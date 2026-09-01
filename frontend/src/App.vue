<template>
  <LoginPage v-if="!authed" @login="handleLogin" />

  <div v-else class="app-shell">
    <!-- 顶部 Header -->
    <header class="app-header">
      <div class="header-left">
        <div class="logo-icon" aria-hidden="true">P</div>
        <h1>客户业绩保费分析系统</h1>
      </div>
      <div class="header-right">
        <span class="header-subtitle">Premium Analysis System</span>
        <el-tag v-if="mockMode" type="warning" effect="plain" size="small">Mock</el-tag>
        <el-button v-if="!mockMode" size="small" text bg @click="handleLogout">退出登录</el-button>
      </div>
    </header>

    <!-- 主体布局：左侧步骤栏 + 右侧内容区 -->
    <div class="app-body">
      <!-- 左侧步骤栏（仅 step>=1 时显示） -->
      <aside v-if="step >= 1" class="app-sidebar" aria-label="流程进度">
        <div class="sidebar-header">
          <span class="sidebar-label">流程进度</span>
        </div>
        <div class="sidebar-steps-wrap">
          <div class="sidebar-steps">
            <div
              v-for="(s, i) in steps"
              :key="s.title"
              class="step-row"
              :class="{
                'is-done': i < step,
                'is-active': i === step,
                'is-clickable': s.reachable()
              }"
              :aria-current="i === step ? 'step' : undefined"
              @click="s.reachable() && goToStep(i)"
            >
              <span class="step-dot">{{ i < step ? '✓' : i + 1 }}</span>
              <span class="step-body">
                <span class="step-title">{{ s.title }}</span>
                <span class="step-desc">{{ s.desc }}</span>
              </span>
            </div>
          </div>
        </div>
        <div class="sidebar-footer">
          <div class="sidebar-tip">
            <span class="tip-dot" aria-hidden="true"></span>
            <span>数据仅在内存中处理，不会落盘存储</span>
          </div>
        </div>
      </aside>

      <!-- 主内容区 -->
      <main class="app-main">
        <Transition name="fade-slide" mode="out-in">
          <UploadPage
            v-if="step === 0"
            key="upload"
            @uploaded="onUploaded"
          />
          <MappingStep
            v-else-if="step === 1"
            key="mapping"
            :upload="uploadResult"
            @back="goBackToUpload"
            @confirm="onConfirmMapping"
          />
          <ResultPage
            v-else
            key="result"
            :session-id="uploadResult ? uploadResult.session_id : ''"
            :mapping="currentMapping"
            @reupload="reset"
            @session-expired="onSessionExpired"
          />
        </Transition>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import UploadPage from './components/UploadPage.vue'
import MappingStep from './components/MappingStep.vue'
import ResultPage from './components/ResultPage.vue'
import LoginPage from './components/LoginPage.vue'
import { isMockMode, getToken, setToken, clearToken, logout, onAuthFail } from './api/client'

const mockMode = isMockMode()

// 登录门禁：Mock 模式自动放行；真实后端要求有效 Token
const authed = ref(mockMode ? true : !!getToken())

function handleLogin(token) {
  setToken(token)
  authed.value = true
}

async function handleLogout() {
  await logout()
  authed.value = false
}

// Token 失效（401）时统一跳回登录页
onMounted(() => {
  onAuthFail(() => {
    clearToken()
    authed.value = false
  })
})

const step = ref(0)
const uploadResult = ref(null)
const currentMapping = ref(null)

/** 步骤元信息（reachable 决定该步是否可点击跳转） */
const steps = [
  { title: '上传文件', desc: '导入 Excel 数据', reachable: () => step.value > 0 },
  { title: '确认列映射', desc: '校验字段对应关系', reachable: () => !!uploadResult.value },
  { title: '分析结果', desc: '业绩统计与异常分析', reachable: () => !!uploadResult.value && !!currentMapping.value }
]

/** 点击步骤导航（不丢失已有数据） */
function goToStep(target) {
  if (target === 0) {
    // 回到上传 = 明确重新开始，与"重新上传"语义一致
    reset()
    return
  }
  if (target === 1 && uploadResult.value) {
    step.value = 1
    return
  }
  if (target === 2 && uploadResult.value && currentMapping.value) {
    step.value = 2
    return
  }
}

function onUploaded(res) {
  uploadResult.value = res
  // 流程衔接：上传成功直接进入列映射（映射已按 auto_mapping 预填），
  // 原始数据预览可在映射页折叠查看，无需在预览页停留再点一次"下一步"
  const auto = res.auto_mapping || {}
  const allAuto = ['customer', 'date', 'premium', 'policies'].every((k) => !!auto[k])
  step.value = 1
  ElMessage.success(allAuto ? '上传成功，已自动识别全部字段，请确认映射后继续' : '上传成功，部分字段需手动指定，请在映射页确认')
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

/** 从列映射返回上传（仅当尚未分析时允许，避免误丢结果） */
function goBackToUpload() {
  reset()
}

function reset() {
  step.value = 0
  uploadResult.value = null
  currentMapping.value = null
}

</script>

<style scoped>
/* 主体 flex 布局：侧边栏 + 内容区 */
.app-body {
  display: flex;
  flex: 1;
  min-height: 0;
}

/* 左侧步骤栏：Parchment 表面 */
.app-sidebar {
  width: 240px;
  flex-shrink: 0;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--color-border-light);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 侧边栏顶部标签 */
.sidebar-header {
  padding: 20px 20px 12px;
  flex-shrink: 0;
}
.sidebar-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
  letter-spacing: 0.6px;
}

/* 步骤区 */
.sidebar-steps-wrap {
  flex: 1;
  padding: 12px 16px;
  overflow-y: auto;
}
.sidebar-steps {
  display: flex;
  flex-direction: column;
}

/* 单个步骤 */
.step-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 10px;
  border-radius: var(--radius-md);
  position: relative;
  transition: background-color 0.2s ease;
}
/* 步骤间连接线（在非最后一步下方） */
.step-row:not(:last-child)::after {
  content: '';
  position: absolute;
  left: 23px;
  top: 44px;
  bottom: -8px;
  width: 2px;
  background: var(--color-border);
}

.step-dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  background: var(--color-border);
  color: #ffffff;
  transition: background-color 0.2s ease;
  z-index: 1;
}

.step-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.step-title {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.224px;
  color: var(--color-text-muted);
  transition: color 0.2s ease;
}
.step-desc {
  font-size: 12px;
  color: var(--color-text-muted);
  letter-spacing: -0.12px;
}

/* 已完成步骤：绿圈 + ✓ */
.step-row.is-done .step-dot {
  background: var(--color-success);
}
.step-row.is-done .step-title {
  color: var(--color-text-primary);
}

/* 当前步骤：黑底高亮 + 蓝圈 */
.step-row.is-active {
  background: #1d1d1f;
}
.step-row.is-active .step-dot {
  background: var(--color-primary);
}
.step-row.is-active .step-title {
  color: #ffffff;
}
.step-row.is-active .step-desc {
  color: #86868b;
}

/* 可点击态 */
.step-row.is-clickable {
  cursor: pointer;
}
.step-row.is-clickable:not(.is-active):hover {
  background: #ececed;
}

/* 侧边栏底部提示 */
.sidebar-footer {
  flex-shrink: 0;
  padding: 12px 16px 20px;
}
.sidebar-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--color-text-muted);
  line-height: 1.5;
  background: var(--bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  padding: 10px 12px;
}
.tip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-success);
  flex-shrink: 0;
}

/* 主内容区：占满剩余宽度 */
.app-main {
  flex: 1;
  min-width: 0;
  padding: var(--spacing-lg);
  overflow-y: auto;
}

/* 移动端：横向步骤条在顶部，内容区在上方可滚动 */
@media (max-width: 768px) {
  .app-sidebar {
    width: 100%;
    flex-shrink: 0;
    border-right: none;
    border-bottom: 1px solid var(--color-border-light);
    flex-direction: column;
  }
  .sidebar-header {
    display: none;
  }
  .sidebar-steps-wrap {
    padding: 8px 12px;
    overflow-x: auto;
  }
  .sidebar-steps {
    flex-direction: row;
    gap: 8px;
  }
  .step-row {
    flex: 1;
    padding: 8px;
  }
  /* 移动端改为横向，连接线变成右侧横向短线 */
  .step-row:not(:last-child)::after {
    left: auto;
    right: -8px;
    top: 22px;
    bottom: auto;
    width: 8px;
    height: 2px;
  }
  .step-desc {
    display: none;
  }
  .step-title {
    font-size: 12px;
  }
  .sidebar-footer {
    display: none;
  }
}
</style>
