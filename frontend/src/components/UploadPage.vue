<template>
  <div>
    <div class="card">
      <h2 class="card-title">上传 Excel 文件</h2>
      <el-upload
        ref="uploadRef"
        drag
        :auto-upload="false"
        :limit="1"
        accept=".xlsx,.xls"
        :class="{ 'is-dragover': isDragOver }"
        :disabled="uploading"
        :on-change="onFileChange"
        :on-exceed="onExceed"
        :on-remove="onRemove"
        @dragenter="isDragOver = true"
        @dragleave="onDragLeave"
        @drop="isDragOver = false"
      >
        <el-icon class="el-icon--upload"><upload-filled /></el-icon>
        <div class="el-upload__text">
          <template v-if="uploading">正在解析文件，请稍候…</template>
          <template v-else>将文件拖到此处，或<em>点击上传</em></template>
        </div>
        <template #tip>
          <div class="el-upload__tip">仅支持 .xlsx / .xls 格式，大小不超过 50MB；需包含签单时间、客户代码、保费量、出单量等列</div>
        </template>
      </el-upload>

      <!-- 已选文件反馈卡片 -->
      <div v-if="selectedFile && !uploading" class="file-feedback" role="status" aria-live="polite">
        <el-icon class="file-feedback-icon"><Document /></el-icon>
        <div class="file-feedback-info">
          <span class="file-feedback-name" :title="selectedFile.name">{{ selectedFile.name }}</span>
          <span class="file-feedback-meta">{{ formatSize(selectedFile.size) }} · Excel 文件</span>
        </div>
        <el-button text size="small" class="file-feedback-remove" @click="clearFile">
          <el-icon><Close /></el-icon>
          <span>移除</span>
        </el-button>
      </div>

      <div class="upload-actions">
        <el-button
          type="primary"
          :loading="uploading"
          :disabled="!selectedFile || uploading"
          @click="doUpload"
        >
          {{ uploading ? '上传中…' : '开始上传' }}
        </el-button>
        <span v-if="!selectedFile" class="muted upload-hint-inline">请先选择 Excel 文件</span>
      </div>
    </div>

    <template v-if="result">
      <div v-if="result.warnings && result.warnings.length" class="card">
        <el-alert
          v-for="(w, i) in result.warnings"
          :key="i"
          :title="w"
          type="warning"
          show-icon
          :closable="false"
          style="margin-bottom: calc(var(--fs-base) * 0.5)"
        />
      </div>

      <div class="card">
        <div class="card-head-row">
          <h2 class="card-title" style="margin: 0">数据预览（前 {{ result.preview_rows.length }} 行）</h2>
          <span class="muted">共识别 {{ result.columns.length }} 列</span>
        </div>
        <div class="table-scroll" style="margin-top: var(--spacing-md)">
          <el-table :data="previewData" border size="small">
            <el-table-column
              v-for="col in result.columns"
              :key="col"
              :prop="col"
              :label="col"
              min-width="120"
            />
          </el-table>
        </div>
        <el-button
          ref="nextBtnRef"
          type="primary"
          style="margin-top: calc(var(--fs-base) * 0.75)"
          @click="emit('uploaded', result)"
        >
          下一步：确认列映射
          <el-icon class="el-icon--right"><ArrowRight /></el-icon>
        </el-button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, Document, Close, ArrowRight } from '@element-plus/icons-vue'
import { uploadFile } from '../api/client'

const emit = defineEmits(['uploaded'])

const uploadRef = ref(null)
const selectedFile = ref(null)
const uploading = ref(false)
const result = ref(null)
const isDragOver = ref(false)
const nextBtnRef = ref(null)

/** 拖拽离开：需判断离开目标区域才算结束，避免内部元素抖动 */
function onDragLeave(e) {
  if (!uploadRef.value) return
  const el = uploadRef.value.$el || uploadRef.value
  if (el && !el.contains(e.relatedTarget)) {
    isDragOver.value = false
  }
}

/** 文件大小人性化展示 */
function formatSize(bytes) {
  if (bytes == null) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB'
}

function onFileChange(uploadFileObj) {
  const file = uploadFileObj.raw
  if (!file) return
  const isExcel = /\.(xlsx|xls)$/i.test(file.name)
  if (!isExcel) {
    ElMessage.error('仅支持 .xlsx / .xls 格式的 Excel 文件')
    clearFile()
    return
  }
  if (file.size > 50 * 1024 * 1024) {
    ElMessage.error('文件大小超过 50MB 限制')
    clearFile()
    return
  }
  selectedFile.value = file
  result.value = null // 更换文件后清除旧预览，防止混淆
}

function onExceed() {
  ElMessage.warning('一次仅支持上传一个文件，请先移除已选文件')
}

function onRemove() {
  selectedFile.value = null
  result.value = null
}

function clearFile() {
  selectedFile.value = null
  result.value = null
  uploadRef.value?.clearFiles()
}

async function doUpload() {
  if (!selectedFile.value || uploading.value) return
  uploading.value = true
  isDragOver.value = false
  try {
    const res = await uploadFile(selectedFile.value)
    result.value = res
    // 流程衔接：上传成功即进入列映射（App 统一跳转，映射已按 auto_mapping 预填），
    // 原始预览在映射页折叠查看，无需在本页再点一次"下一步"
    emit('uploaded', res)
  } catch (err) {
    ElMessage.error('上传失败：' + (err.response?.data?.detail || err.message || '未知错误'))
  } finally {
    uploading.value = false
  }
}

// 将 preview_rows 二维数组转为 el-table 可用的对象数组
const previewData = computed(() => {
  if (!result.value) return []
  const cols = result.value.columns
  return result.value.preview_rows.map((row) => {
    const obj = {}
    cols.forEach((col, i) => {
      obj[col] = row[i]
    })
    return obj
  })
})
</script>

<style scoped>
.upload-area {
  border: 2px dashed var(--color-border);
  border-radius: var(--radius-md);
  padding: 48px 24px;
  text-align: center;
  background: var(--bg-table-header);
  transition: all 0.3s ease;
  cursor: pointer;
}
.upload-area:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}
.upload-area .el-icon {
  font-size: 48px;
  color: var(--color-text-muted);
  margin-bottom: 16px;
}
.upload-area .upload-text {
  font-size: var(--fs-lg);
  color: var(--color-text-primary);
  margin-bottom: 8px;
}
.upload-area .upload-hint {
  font-size: var(--fs-sm);
  color: var(--color-text-muted);
}

/* el-upload 拖拽区域覆盖 */
:deep(.el-upload-dragger) {
  border: 2px dashed var(--color-border);
  border-radius: var(--radius-md);
  padding: 48px 24px;
  background: var(--bg-table-header);
  transition: border-color 0.25s ease, background-color 0.25s ease, transform 0.25s ease;
}
:deep(.el-upload-dragger:hover) {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}
:deep(.el-upload-dragger .el-icon) {
  font-size: 48px;
  color: var(--color-text-muted);
}
:deep(.el-upload-dragger .el-upload__text) {
  color: var(--color-text-primary);
}

/* 拖拽悬停高亮：整块区域变色 + 轻微放大（仅 transform） */
.is-dragover :deep(.el-upload-dragger) {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
  transform: scale(1.01);
}
.is-dragover :deep(.el-upload-dragger .el-icon) {
  color: var(--color-primary);
}
.is-dragover :deep(.el-upload-dragger .el-upload__text) {
  color: var(--color-primary);
  font-weight: 600;
}

/* 上传中禁用拖拽区域交互 */
:deep(.el-upload.is-disabled .el-upload-dragger) {
  cursor: not-allowed;
  opacity: 0.7;
}

/* 已选文件反馈卡片 */
.file-feedback {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: var(--spacing-md);
  padding: var(--spacing-sm) var(--spacing-md);
  background: var(--bg-hover);
  border: 1px solid var(--color-primary-light);
  border-radius: var(--radius-md);
  animation: file-in 0.25s ease;
}
@keyframes file-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
.file-feedback-icon {
  font-size: 22px;
  color: var(--color-primary);
  flex-shrink: 0;
}
.file-feedback-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.file-feedback-name {
  font-size: var(--fs-base);
  font-weight: 600;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-feedback-meta {
  font-size: var(--fs-sm);
  color: var(--color-text-muted);
}
.file-feedback-remove {
  flex-shrink: 0;
}

/* 上传按钮行 */
.upload-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: var(--spacing-md);
}
.upload-hint-inline {
  font-size: var(--fs-sm);
}

/* 预览卡片标题行 */
.card-head-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
