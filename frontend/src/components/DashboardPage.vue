<template>
  <div>
    <!-- 顶部筛选条：时间维度 + 起止期 -->
    <div class="filter-bar">
      <span class="muted">时间维度：</span>
      <el-radio-group v-model="dim" @change="onDimChange">
        <el-radio-button value="monthly">月</el-radio-button>
        <el-radio-button value="quarterly">季</el-radio-button>
        <el-radio-button value="yearly">年</el-radio-button>
      </el-radio-group>

      <span class="muted">起止期：</span>
      <el-select v-model="start" style="width: 150px" @change="onStartChange">
        <el-option v-for="p in periods" :key="p" :label="p" :value="p" />
      </el-select>
      <span class="muted">至</span>
      <el-select v-model="end" style="width: 150px">
        <el-option v-for="p in periods" :key="p" :label="p" :value="p" />
      </el-select>

      <el-button link type="primary" :disabled="isFullRange" @click="resetRange">重置为全量</el-button>
      <span class="muted">共 {{ filtered.length }} 期</span>
    </div>

    <!-- 趋势图：保费折线 + 单量柱状双 Y 轴 + 新增客户数小图 -->
    <TrendChart :data="filtered" />

    <!-- 年度对比 -->
    <YearCompare :data="performance.year_compare" />

    <!-- 当前维度明细表 -->
    <h3 class="card-title" style="margin-top: calc(var(--fs-base) * 1)">明细数据（{{ dimLabel }}）</h3>
    <div class="table-scroll">
      <el-table :data="filtered" border stripe size="small">
        <el-table-column prop="period" label="期间" width="120" sortable />
        <el-table-column label="保费" min-width="140" sortable prop="premium" align="right">
          <template #default="{ row }">{{ fmtMoney(row.premium) }}</template>
        </el-table-column>
        <el-table-column prop="policies" label="出单量" min-width="110" sortable align="right" />
        <el-table-column prop="new_customers" label="新增客户" min-width="110" sortable align="right" />
        <el-table-column prop="active_customers" label="活跃客户" min-width="110" sortable align="right" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import TrendChart from './TrendChart.vue'
import YearCompare from './YearCompare.vue'
import { fmtMoney } from '../utils/format'

const props = defineProps({
  // performance: monthly / quarterly / yearly / year_compare
  performance: { type: Object, required: true }
})

const dim = ref('monthly') // monthly | quarterly | yearly
const dimLabel = computed(() => ({ monthly: '月度', quarterly: '季度', yearly: '年度' }[dim.value]))

// 当前维度对应序列
const series = computed(() => props.performance[dim.value] || [])
const periods = computed(() => series.value.map((item) => item.period))

const start = ref('')
const end = ref('')

// 维度变化时重置起止期为全量
function resetRange() {
  start.value = periods.value[0] || ''
  end.value = periods.value[periods.value.length - 1] || ''
}
function onDimChange() {
  resetRange()
}
// 起点变化时保证 end >= start
function onStartChange(val) {
  const idx = periods.value.indexOf(val)
  const endIdx = periods.value.indexOf(end.value)
  if (endIdx < idx) end.value = val
}

watch(
  () => props.performance,
  () => resetRange(),
  { immediate: true }
)

const isFullRange = computed(
  () => start.value === periods.value[0] && end.value === periods.value[periods.value.length - 1]
)

// 按起止期裁剪序列（前端只做展示筛选，零计算）
const filtered = computed(() => {
  const list = series.value
  const i = list.findIndex((r) => r.period === start.value)
  const j = list.findIndex((r) => r.period === end.value)
  if (i === -1 || j === -1) return list
  return list.slice(Math.min(i, j), Math.max(i, j) + 1)
})
</script>
