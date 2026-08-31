<template>
  <div class="card">
    <h2 class="card-title">数据摘要</h2>
    <div class="summary-grid">
      <div class="summary-item">
        <div class="label">总行数</div>
        <div class="value">{{ fmtNum(summary.total_rows) }}</div>
      </div>
      <div class="summary-item">
        <div class="label">有效行</div>
        <div class="value val-up">{{ fmtNum(summary.valid_rows) }}</div>
      </div>
      <div
        class="summary-item summary-item-interactive"
        role="button"
        tabindex="0"
        :aria-expanded="showInvalid ? 'true' : 'false'"
        aria-controls="invalid-samples-panel"
        @click="showInvalid = !showInvalid"
        @keydown.enter.prevent="showInvalid = !showInvalid"
        @keydown.space.prevent="showInvalid = !showInvalid"
      >
        <div class="label">无效行（点击{{ showInvalid ? '收起' : '展开' }}样例）</div>
        <div class="value val-down">
          {{ fmtNum(summary.invalid_rows) }}
          <el-icon class="expand-icon" :class="{ 'is-expanded': showInvalid }"><ArrowDown /></el-icon>
        </div>
      </div>
      <div class="summary-item">
        <div class="label">重复行</div>
        <div class="value">{{ fmtNum(summary.duplicate_rows) }}</div>
      </div>
      <div class="summary-item">
        <div class="label">客户数</div>
        <div class="value">{{ fmtNum(summary.customer_count) }}</div>
      </div>
      <div class="summary-item">
        <div class="label">月份范围</div>
        <div class="value">{{ monthRangeText }}</div>
      </div>
    </div>

    <div
      v-if="showInvalid && summary.invalid_samples?.length"
      id="invalid-samples-panel"
      class="table-scroll"
      style="margin-top: calc(var(--fs-base) * 1)"
    >
      <el-table :data="summary.invalid_samples" border size="small">
        <el-table-column prop="row" label="行号" width="90" />
        <el-table-column prop="reason" label="无效原因" min-width="160" />
        <el-table-column label="原始数据" min-width="320">
          <template #default="{ row }">
            <span class="muted">{{ JSON.stringify(row.raw) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { fmtNum } from '../utils/format'

const props = defineProps({
  summary: { type: Object, required: true } // summary: total_rows/valid_rows/invalid_rows/duplicate_rows/invalid_samples/customer_count/month_range
})

const showInvalid = ref(false)

const monthRangeText = computed(() => {
  const range = props.summary.month_range
  return range && range.length === 2 ? `${range[0]} ~ ${range[1]}` : '-'
})
</script>

<style scoped>
/* 摘要卡片内部布局强化 - 浅色主题 */
.card .summary-grid {
  margin-top: var(--spacing-xs);
}

/* 无效行展开表格 */
.card .table-scroll {
  margin-top: var(--spacing-md);
}

/* 可交互摘要项（无效行展开） */
.summary-item-interactive {
  cursor: pointer;
  user-select: none;
  position: relative;
}
.summary-item-interactive:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
.summary-item-interactive:hover {
  border-color: var(--color-primary-light);
}
.expand-icon {
  vertical-align: middle;
  margin-left: 4px;
  font-size: 13px;
  color: var(--color-text-muted);
  transition: transform 0.2s ease;
}
.expand-icon.is-expanded {
  transform: rotate(180deg);
}
</style>
