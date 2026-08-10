<template>
  <div class="card">
    <h2 class="card-title">确认列映射</h2>

    <el-alert
      v-if="upload.need_manual || hasNullMapping"
      type="warning"
      :closable="false"
      show-icon
      title="系统未能自动识别全部列，请手动选择四个字段对应的 Excel 列后再继续。"
      style="margin-bottom: calc(var(--fs-base) * 1)"
    />

    <div class="filter-bar">
      <el-form-item v-for="field in fields" :key="field.key" :label="field.label" style="margin-bottom: 0">
        <el-select
          v-model="mapping[field.key]"
          :placeholder="`请选择${field.label}对应的列`"
          clearable
          style="width: 220px"
        >
          <el-option v-for="col in upload.columns" :key="col" :label="col" :value="col" />
        </el-select>
      </el-form-item>
    </div>

    <p v-if="duplicateTip" class="muted" style="color: var(--color-down)">{{ duplicateTip }}</p>
    <p class="muted">四个字段必须分别选择不同的列；全部选齐后才可开始分析。</p>

    <div style="display: flex; gap: calc(var(--fs-base) * 0.75); margin-top: calc(var(--fs-base) * 0.5)">
      <el-button @click="emit('back')">返回重新上传</el-button>
      <el-button type="primary" :loading="loading" :disabled="!canContinue" @click="confirm">
        开始分析
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  upload: { type: Object, required: true }, // /api/upload 返回结果
  loading: { type: Boolean, default: false }
})
const emit = defineEmits(['back', 'confirm'])

const fields = [
  { key: 'customer', label: '客户代码' },
  { key: 'date', label: '签单时间' },
  { key: 'premium', label: '保费量' },
  { key: 'policies', label: '出单量' }
]

// 预填 auto_mapping（值可能为 null）
const mapping = reactive({
  customer: props.upload.auto_mapping?.customer ?? null,
  date: props.upload.auto_mapping?.date ?? null,
  premium: props.upload.auto_mapping?.premium ?? null,
  policies: props.upload.auto_mapping?.policies ?? null
})

const hasNullMapping = computed(() => fields.some((f) => !mapping[f.key]))

const duplicateTip = computed(() => {
  const values = fields.map((f) => mapping[f.key]).filter(Boolean)
  const set = new Set(values)
  return set.size < values.length ? '存在重复选择的列，请确保四个字段对应不同的列。' : ''
})

const canContinue = computed(() => !hasNullMapping.value && !duplicateTip.value)

function confirm() {
  if (!canContinue.value) {
    ElMessage.warning('请先选齐四个字段对应的列')
    return
  }
  emit('confirm', { ...mapping })
}
</script>

<style scoped>
.mapping-step {
  font-size: var(--fs-base);
}
.mapping-step .mapping-card {
  background: var(--bg-card);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  padding: var(--spacing-lg);
}
</style>
