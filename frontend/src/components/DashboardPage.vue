<template>
  <div class="dashboard-page">
    <!-- 开始分析按钮 -->
    <div v-if="!performanceData" class="dashboard-start-area">
      <el-button type="primary" size="large" :loading="analyzing" @click="startAnalysis">
        开始分析
      </el-button>
    </div>

    <!-- 数据概要 -->
    <SummaryBar v-if="summary" :summary="summary" />

    <!-- 分析结果内容 -->
    <template v-if="performanceData">
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
    <YearCompare :data="performanceData.year_compare" />

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
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import TrendChart from './TrendChart.vue'
import YearCompare from './YearCompare.vue'
import SummaryBar from './SummaryBar.vue'
import { fmtMoney } from '../utils/format'
import { analyze, SESSION_EXPIRED } from '../api/client.js'

const props = defineProps({
  sessionId: { type: String, default: '' },
  mapping: { type: Object, default: () => ({}) }
})
const emit = defineEmits(['range-change', 'session-expired'])

// 内部状态
const analyzing = ref(false)
const summary = ref(null)
const performanceData = ref(null)

const dim = ref('monthly') // monthly | quarterly | yearly
const dimLabel = computed(() => ({ monthly: '月度', quarterly: '季度', yearly: '年度' }[dim.value]))

// 当前维度对应序列
const series = computed(() => performanceData.value?.[dim.value] || [])
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

watch(performanceData, () => {
  if (performanceData.value) resetRange()
})

// 监听时间维度和起止期变化，向父组件 emit 月度维度的起止期
// AiAnomalyPanel 需要月度格式的起止期来动态筛选数据
watch(
  [start, end, dim],
  () => {
    // 始终传递月度维度的起止期（不管当前维度是什么）
    // 月度序列始终存在于 performance.monthly 中
    const monthlySeries = performanceData.value?.monthly || []
    const monthlyPeriods = monthlySeries.map((item) => item.period)
    // 尝试将当前起止期映射到月度序列
    // period 格式: 月度="2025-10", 季度="25Q4", 年度="2025"
    let mStart = ''
    let mEnd = ''
    if (dim.value === 'monthly') {
      // 月度维度直接使用当前起止期
      mStart = start.value
      mEnd = end.value
    } else {
      // 季度/年度维度：传递月度全量范围（让后端用默认 REQUIRED_MONTHS）
      mStart = monthlyPeriods[0] || ''
      mEnd = monthlyPeriods[monthlyPeriods.length - 1] || ''
    }
    emit('range-change', { start: mStart, end: mEnd })
  },
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

// 开始分析
async function startAnalysis() {
  analyzing.value = true
  try {
    const res = await analyze(props.sessionId, props.mapping)
    summary.value = res.summary
    performanceData.value = res.performance
  } catch (err) {
    if (err.code === SESSION_EXPIRED) {
      emit('session-expired')
    } else {
      ElMessage.error('分析失败：' + (err.message || '未知错误'))
    }
  } finally {
    analyzing.value = false
  }
}
</script>

<style scoped>
.dashboard-page {
  padding: 0;
}

/* 筛选区域 */
.dashboard-page .filter-section {
  background: var(--bg-hover);
  border-radius: var(--radius-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  margin-bottom: var(--spacing-md);
  border: 1px solid var(--color-border-light);
}

/* 图表卡片 */
.dashboard-page .chart-card {
  background: var(--bg-card);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  padding: var(--spacing-md);
  margin-bottom: var(--spacing-md);
  border: 1px solid var(--color-border-light);
  transition: box-shadow 0.2s ease;
}

.dashboard-page .chart-card:hover {
  box-shadow: var(--shadow-md);
}

/* 图表标题 */
.dashboard-page .chart-title {
  font-size: var(--fs-base);
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-sm);
  padding-left: 12px;
  border-left: 3px solid var(--color-primary);
  line-height: 1.4;
}

/* 表格区域 */
.dashboard-page .table-section {
  background: var(--bg-card);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  padding: var(--spacing-md);
  border: 1px solid var(--color-border-light);
}

/* 年度对比区域 */
.dashboard-page .compare-section {
  margin-top: var(--spacing-md);
}

.dashboard-start-area {
  display: flex;
  justify-content: center;
  padding: 40px 0;
}

/* 响应式 */
@media (max-width: 768px) {
  .dashboard-page .chart-card {
    padding: var(--spacing-sm);
  }
}
</style>
