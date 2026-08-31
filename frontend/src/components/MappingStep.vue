<template>
  <div class="card">
    <div class="card-head-row">
      <h2 class="card-title" style="margin: 0">确认列映射</h2>
      <span class="muted file-meta" v-if="upload.file_name">
        <el-icon><Document /></el-icon>
        {{ upload.file_name }}
      </span>
    </div>

    <!-- 流程状态提示：全识别成功 → 绿色；需手动 → 橙色列出缺失字段 -->
    <el-alert
      v-if="!needManual"
      type="success"
      :closable="false"
      show-icon
      title="已自动识别全部字段，确认无误后点击「下一步」即可"
      style="margin-bottom: calc(var(--fs-base) * 1)"
    />
    <el-alert
      v-else
      type="warning"
      :closable="false"
      show-icon
      :title="'以下字段未自动识别，请手动选择：' + missingFields.join('、')"
      style="margin-bottom: calc(var(--fs-base) * 1)"
    />

    <div class="filter-bar mapping-fields">
      <div
        v-for="field in fields"
        :key="field.key"
        class="mapping-field"
        :class="{ 'is-duplicate': isDuplicate(field.key) }"
      >
        <div class="mapping-field-label">
          <span class="mapping-label-text">{{ field.label }}</span>
          <el-tag
            v-if="isAutoDetected(field.key)"
            type="success"
            size="small"
            effect="light"
          >自动识别</el-tag>
          <el-tag
            v-else-if="mapping[field.key]"
            type="warning"
            size="small"
            effect="plain"
          >手动选择</el-tag>
        </div>
        <el-select
          v-model="mapping[field.key]"
          :placeholder="`请选择${field.label}对应的列`"
          clearable
          style="width: 220px"
        >
          <el-option v-for="col in upload.columns" :key="col" :label="col" :value="col" />
        </el-select>
      </div>
    </div>

    <div class="mapping-feedback" role="status" aria-live="polite">
      <template v-if="duplicateTip">
        <span class="feedback-error">{{ duplicateTip }}</span>
      </template>
      <template v-else-if="missingFields.length">
        <span class="feedback-warn">以下字段尚未选择：{{ missingFields.join('、') }}</span>
      </template>
      <template v-else>
        <span class="feedback-ok">✓ 四个字段均已配置，可以开始分析</span>
      </template>
    </div>

    <!-- 映射结果实时预览：降低选错列风险 -->
    <div v-if="allMapped && !duplicateTip" class="preview-section">
      <div class="preview-section-title">
        <el-icon><View /></el-icon>
        <span>映射结果预览（每字段取前 {{ sampleCount }} 行样例）</span>
      </div>
      <div class="table-scroll">
        <el-table :data="mappingPreviewRows" border size="small">
          <el-table-column prop="field" label="字段" width="110" />
          <el-table-column prop="column" label="映射列" min-width="120" />
          <el-table-column label="样例数据" min-width="280">
            <template #default="{ row }">
              <span class="sample-values">{{ row.samples.join('、') }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- 原始数据预览（可折叠，替代上传页停留查看） -->
    <el-collapse class="raw-preview" v-model="rawPreviewOpen">
      <el-collapse-item name="raw" title="查看原始数据预览（前 5 行）">
        <div class="table-scroll">
          <el-table :data="rawPreviewRows" border size="small">
            <el-table-column
              v-for="col in upload.columns"
              :key="col"
              :prop="col"
              :label="col"
              min-width="120"
            />
          </el-table>
        </div>
      </el-collapse-item>
    </el-collapse>

    <div style="display: flex; gap: calc(var(--fs-base) * 0.75); margin-top: calc(var(--fs-base) * 0.5)">
      <el-button @click="emit('back')">返回重新上传</el-button>
      <el-button
        type="primary"
        :loading="loading"
        :disabled="!canContinue"
        @click="confirm"
        :aria-label="canContinue ? '确认映射并进入分析' : '请先完成字段映射'"
      >
        下一步：开始分析
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { reactive, computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, View } from '@element-plus/icons-vue'

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

const sampleCount = 5
const rawPreviewOpen = ref([])

// 预填 auto_mapping（值可能为 null）
const mapping = reactive({
  customer: props.upload.auto_mapping?.customer ?? null,
  date: props.upload.auto_mapping?.date ?? null,
  premium: props.upload.auto_mapping?.premium ?? null,
  policies: props.upload.auto_mapping?.policies ?? null
})

/** 该字段是否为后端自动识别 */
function isAutoDetected(key) {
  return !!props.upload.auto_mapping?.[key] && !!mapping[key]
}

/** 是否需要手动指定（后端 need_manual 或存在未选字段） */
const needManual = computed(() => props.upload.need_manual || missingFields.value.length > 0)

/** 已选择列中重复出现的列名集合 */
const duplicateColumns = computed(() => {
  const values = fields.map((f) => mapping[f.key]).filter(Boolean)
  const seen = new Set()
  const dups = new Set()
  for (const v of values) {
    if (seen.has(v)) dups.add(v)
    seen.add(v)
  }
  return dups
})

function isDuplicate(key) {
  return mapping[key] && duplicateColumns.value.has(mapping[key])
}

const missingFields = computed(() =>
  fields.filter((f) => !mapping[f.key]).map((f) => f.label)
)

const duplicateTip = computed(() => {
  if (!duplicateColumns.value.size) return ''
  const names = fields.filter((f) => duplicateColumns.value.has(mapping[f.key])).map((f) => f.label)
  return '存在重复选择的列：' + names.join('、') + ' 使用了同一列，请确保四个字段对应不同的列。'
})

const allMapped = computed(() => fields.every((f) => !!mapping[f.key]))
const canContinue = computed(() => allMapped.value && !duplicateTip.value)

/** 原始预览：二维数组 → 对象数组（与上传页一致） */
const rawPreviewRows = computed(() => {
  const cols = props.upload.columns || []
  return (props.upload.preview_rows || []).map((row) => {
    const obj = {}
    cols.forEach((col, i) => {
      obj[col] = row[i]
    })
    return obj
  })
})

/** 映射结果实时预览：按当前 mapping 提取每字段所选列的样例 */
const mappingPreviewRows = computed(() => {
  if (!allMapped.value) return []
  const cols = props.upload.columns || []
  const rows = props.upload.preview_rows || []
  return fields.map((f) => {
    const col = mapping[f.key]
    const colIdx = cols.indexOf(col)
    const samples = rows.slice(0, sampleCount).map((r) => (colIdx >= 0 ? r[colIdx] : '-'))
    return { field: f.label, column: col, samples }
  })
})

function confirm() {
  if (!canContinue.value) {
    ElMessage.warning('请先选齐四个字段对应的列，且不能重复')
    return
  }
  emit('confirm', { ...mapping })
}
</script>

<style scoped>
.card-head-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.file-meta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.mapping-fields {
  align-items: flex-start;
  padding: var(--spacing-md);
}
.mapping-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--spacing-sm);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  transition: border-color 0.2s ease, background-color 0.2s ease;
}
.mapping-field:hover {
  background: var(--bg-card);
}
/* 重复列：红色警示边框（同时配合文字提示，不只靠颜色） */
.mapping-field.is-duplicate {
  border-color: var(--color-danger);
  background: rgba(234, 67, 53, 0.04);
}
.mapping-field.is-duplicate :deep(.el-select__wrapper) {
  box-shadow: 0 0 0 1px var(--color-danger) inset;
}
.mapping-field-label {
  display: flex;
  align-items: center;
  gap: 6px;
}
.mapping-label-text {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--color-text-secondary);
}

/* 校验反馈区 */
.mapping-feedback {
  margin-top: var(--spacing-sm);
  font-size: var(--fs-sm);
  min-height: 20px;
}
.feedback-ok { color: var(--color-success); font-weight: 500; }
.feedback-warn { color: #b45309; }
.feedback-error { color: var(--color-danger); }

/* 映射结果预览 */
.preview-section {
  margin-top: var(--spacing-md);
  padding: var(--spacing-sm) var(--spacing-md) var(--spacing-md);
  background: var(--bg-hover);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
}
.preview-section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: var(--spacing-sm);
}
.sample-values {
  color: var(--color-text-secondary);
  font-size: var(--fs-sm);
  word-break: break-all;
}

/* 原始数据预览折叠 */
.raw-preview {
  margin-top: var(--spacing-md);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
}
.raw-preview :deep(.el-collapse-item__header) {
  font-size: var(--fs-sm);
  color: var(--color-text-secondary);
  padding-left: var(--spacing-sm);
}
.raw-preview :deep(.el-collapse-item__content) {
  padding: 0 var(--spacing-sm) var(--spacing-sm);
}
</style>
