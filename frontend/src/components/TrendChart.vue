<template>
  <div class="trend-chart">
    <h3 class="card-title">业绩趋势</h3>
    <div class="chart-wrap" :class="{ 'has-empty': !data.length }">
      <div ref="chartRef" class="chart-box"></div>
      <div v-if="!data.length" class="chart-empty">
        <el-icon><DataLine /></el-icon>
        <span>暂无趋势数据</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'
import { DataLine } from '@element-plus/icons-vue'
import { fmtMoney } from '../utils/format'

const props = defineProps({
  // 行序列：[{ period, premium, policies, new_customers, active_customers }]
  data: { type: Array, required: true }
})

const chartRef = ref(null)
let chart = null

function buildOption(rows) {
  const periods = rows.map((r) => r.period)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      valueFormatter: (v) => (typeof v === 'number' ? fmtMoney(v) : v)
    },
    legend: { data: ['保费', '出单量', '新增客户', '活跃客户'] },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 80, right: 70, top: 50, height: '42%' }, // 主图：保费 + 单量
      { left: 80, right: 70, top: '68%', height: '18%' } // 小图：客户数
    ],
    xAxis: [
      { type: 'category', data: periods, gridIndex: 0 },
      { type: 'category', data: periods, gridIndex: 1 }
    ],
    yAxis: [
      { type: 'value', name: '保费', gridIndex: 0, position: 'left' },
      { type: 'value', name: '出单量', gridIndex: 0, position: 'right' },
      { type: 'value', name: '客户数', gridIndex: 1 }
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1] },
      { type: 'slider', xAxisIndex: [0, 1], bottom: 4 }
    ],
    series: [
      {
        name: '保费',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: rows.map((r) => r.premium),
        smooth: true,
        itemStyle: { color: '#0066cc' }
      },
      {
        name: '出单量',
        type: 'bar',
        xAxisIndex: 0,
        yAxisIndex: 1,
        data: rows.map((r) => r.policies),
        itemStyle: { color: '#99c7f0' }
      },
      {
        name: '新增客户',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 2,
        data: rows.map((r) => r.new_customers),
        itemStyle: { color: '#34c759' }
      },
      {
        name: '活跃客户',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 2,
        data: rows.map((r) => r.active_customers),
        itemStyle: { color: '#ff9f0a' }
      }
    ]
  }
}

function render() {
  if (!chart) return
  chart.setOption(buildOption(props.data), true)
}

onMounted(() => {
  chart = echarts.init(chartRef.value) // ECharts 原生 init，不使用 vue-echarts
  render()
  window.addEventListener('resize', onResize)
})

function onResize() {
  chart?.resize()
}

watch(() => props.data, render, { deep: true })

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.trend-chart .chart-wrap {
  position: relative;
  height: 480px;
}
.trend-chart .chart-box {
  width: 100%;
  height: 100%;
}
.trend-chart .chart-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--color-text-muted);
  font-size: var(--fs-base);
  background: var(--bg-card);
  border-radius: var(--radius-md);
  pointer-events: none;
}
.trend-chart .chart-empty .el-icon {
  font-size: 32px;
}
/* 移动端降低图表高度，减少滚动距离 */
@media (max-width: 768px) {
  .trend-chart .chart-wrap {
    height: 340px;
  }
}
</style>
