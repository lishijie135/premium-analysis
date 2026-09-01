<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="login-logo" aria-hidden="true">P</div>
      <h1 class="login-title">客户业绩保费分析系统</h1>
      <p class="login-sub">请登录以继续使用</p>

      <el-form
        class="login-form"
        :model="form"
        @submit.prevent="onSubmit"
        @keyup.enter="onSubmit"
      >
        <el-input
          v-model="form.username"
          class="login-input"
          size="large"
          placeholder="用户名 / 手机号"
          :prefix-icon="User"
          clearable
          autocomplete="username"
        />
        <el-input
          v-model="form.password"
          class="login-input"
          size="large"
          type="password"
          placeholder="密码"
          :prefix-icon="Lock"
          show-password
          autocomplete="current-password"
        />
        <el-button
          class="login-btn"
          size="large"
          type="primary"
          :loading="loading"
          @click="onSubmit"
        >
          {{ loading ? '登录中…' : '登录' }}
        </el-button>
      </el-form>

      <p class="login-tip">账号信息仅用于本系统访问授权，密码经 RSA 加密后传输</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { login } from '../api/client'

const emit = defineEmits(['login'])

const form = ref({ username: '', password: '' })
const loading = ref(false)

async function onSubmit() {
  const { username, password } = form.value
  if (!username || !password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const res = await login(username, password)
    ElMessage.success('登录成功')
    emit('login', res.token)
  } catch (err) {
    const msg = err && err.response && err.response.data && err.response.data.detail
      ? err.response.data.detail
      : (err && err.message) || '登录失败，请重试'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-parchment, #f5f5f7);
  padding: 24px;
}

.login-card {
  width: 380px;
  max-width: 100%;
  background: #ffffff;
  border: 1px solid var(--color-border-light, #e8e8ed);
  border-radius: 18px;
  padding: 40px 32px 32px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.08);
  display: flex;
  flex-direction: column;
  align-items: center;
}

.login-logo {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  background: var(--color-primary, #0066cc);
  color: #fff;
  font-size: 26px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 18px;
}

.login-title {
  font-size: 21px;
  font-weight: 600;
  letter-spacing: -0.3px;
  color: var(--color-text-primary, #1d1d1f);
  margin: 0;
  text-align: center;
}

.login-sub {
  font-size: 14px;
  color: var(--color-text-muted, #86868b);
  margin: 8px 0 28px;
}

.login-form {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.login-input :deep(.el-input__wrapper) {
  border-radius: 11px;
}

.login-btn {
  width: 100%;
  border-radius: 11px;
  font-weight: 600;
  letter-spacing: -0.2px;
  margin-top: 4px;
}

.login-tip {
  font-size: 12px;
  color: var(--color-text-muted, #86868b);
  text-align: center;
  line-height: 1.5;
  margin: 20px 0 0;
}
</style>
