<template>
  <div>
    <h3 class="card-title" style="margin-top: calc(var(--fs-base) * 1)">年度对比</h3>
    <div class="compare-row">
      <div class="compare-chart">
        <div ref="premiumRef" class="chart-box" style="height: 300px"></div>
      </div>
      <div class="compare-chart">
        <div ref="policiesRef" class="chart-box" style="height: 300px"></div>
      </div>
      <div class="compare-table">
        <div class="table-scroll">
          <el-table :data="data.yoy" border stripe size="small">
            <el-table-column prop="year" label="年份" width="90" />
            <el-table-column label="保费同比" min-width="120" align="right" sortable prop="premium_change_pct">
              <template #default="{ row }">
                <span :class="pctClass(row.premium_change_pct)">{{ fmtPct(row.premium_change_pct) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="单量同比" min-width="120" align="right" sortable prop="policies_change_pct">
              <template #default="{ row }">
                <span :class="pctClass(row.policies_change_pct)">{{ fmtPct(row.policies_change_pct) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'
import { fmtPct, pctClass } from '../utils/format'

const props = defineProps({
  // year_compare: years / premium_by_year / policies_by_year / yoy
  data: { type: Object, required: true }
})

const premiumRef = ref(null)
const policiesRef = ref(null)
let premiumChart = null
let policiesChart = null

const MONTHS = Array.from({ length: 12 }, (_, i) => `${i + 1}月`)

function buildOption(title, byYear) {
  return {
    title: { text: title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, data: props.data.years.map(String) },
    grid: { left: 80, right: 20, top: 40, bottom: 50 },
    xAxis: { type: 'category', data: MONTHS },
    yAxis: { type: 'value' },
    series: props.data.years.map((year) => ({
      name: String(year),
      type: 'bar',
      // null 值不渲染（echarts 自动跳过）
      data: byYear[String(year)] || []
    }))
  }
}

function render() {
  if (!premiumChart || !policiesChart) return
  premiumChart.setOption(buildOption('各年月度保费对比', props.data.premium_by_year), true)
  policiesChart.setOption(buildOption('各年月度出单量对比', props.data.policies_by_year), true)
}

function onResize() {
  premiumChart?.resize()
  policiesChart?.resize()
}

onMounted(() => {
  premiumChart = echarts.init(premiumRef.value)
  policiesChart = echarts.init(policiesRef.value)
  render()
  window.addEventListener('resize', onResize)
})

watch(() => props.data, render, { deep: true })

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  premiumChart?.dispose()
  policiesChart?.dispose()
  premiumChart = null
  policiesChart = null
})
</script>
