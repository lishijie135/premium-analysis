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
        :on-change="onFileChange"
        :on-exceed="onExceed"
        :on-remove="onRemove"
      >
        <el-icon class="el-icon--upload"><upload-filled /></el-icon>
        <div class="el-upload__text">将文件拖到此处，或<em>点击上传</em></div>
        <template #tip>
          <div class="el-upload__tip">仅支持 .xlsx / .xls 格式，大小不超过 50MB；需包含签单时间、客户代码、保费量、出单量等列</div>
        </template>
      </el-upload>

      <el-button
        type="primary"
        :loading="uploading"
        :disabled="!selectedFile"
        style="margin-top: calc(var(--fs-base) * 1)"
        @click="doUpload"
      >
        开始上传
      </el-button>
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
        <h2 class="card-title">数据预览（前 {{ result.preview_rows.length }} 行）</h2>
        <div class="table-scroll">
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
        <el-button type="primary" style="margin-top: calc(var(--fs-base) * 0.75)" @click="emit('uploaded', result)">
          下一步：确认列映射
        </el-button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { uploadFile } from '../api/client'

const emit = defineEmits(['uploaded'])

const uploadRef = ref(null)
const selectedFile = ref(null)
const uploading = ref(false)
const result = ref(null)

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
  uploadRef.value?.clearFiles()
}

async function doUpload() {
  if (!selectedFile.value) return
  uploading.value = true
  try {
    const res = await uploadFile(selectedFile.value)
    result.value = res
    ElMessage.success('上传成功，请确认下方预览后进入列映射')
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
