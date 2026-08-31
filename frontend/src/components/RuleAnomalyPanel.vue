<template>
  <div class="rule-anomaly-panel">
    <!-- Mock 模式提示 -->
    <el-alert
      v-if="mockMode"
      type="info"
      :closable="false"
      show-icon
      title="当前为 Mock 预览模式"
      description="规则异常分析将使用模拟数据展示，需设置 VITE_USE_MOCK=false 并连接真实后端。"
    />

    <!-- 当前分析范围提示（与业绩分析筛选联动） -->
    <div v-if="rangeText" class="range-bar">
      <el-icon><Calendar /></el-icon>
      <span>当前分析范围：<strong>{{ rangeText }}</strong></span>
      <span class="range-hint">（跟随业绩分析页的起止期筛选）</span>
    </div>

    <!-- 顶部操作栏 -->
    <div class="action-bar">
      <el-button type="primary" :loading="analyzing" :disabled="!sessionId" @click="runAnalysis">
        {{ analyzing ? '分析中…' : '开始分析' }}
      </el-button>
      <el-button @click="configCollapsed = !configCollapsed">
        {{ configCollapsed ? '展开规则配置' : '收起规则配置' }}
      </el-button>
      <el-button :disabled="!tables.length" @click="exportAllExcel">
        导出全部 Excel
      </el-button>
    </div>

    <!-- 错误提示 -->
    <el-alert v-if="errorMsg" type="error" :closable="true" :title="errorMsg" class="err-alert" @close="errorMsg = ''" />

    <!-- 规则配置面板（默认收起） -->
    <div v-if="!configCollapsed" class="rule-config-panel">
        <div v-loading="loadingRules" class="rule-config-body">
          <div v-if="!rulesConfig.length" class="no-rules">暂无规则配置</div>
          <el-table :data="rulesConfig" stripe border size="small">
            <el-table-column label="规则名称" min-width="160">
              <template #default="{ row }">
                <el-input v-model="row.name" size="small" placeholder="输入规则名称" />
              </template>
            </el-table-column>
            <el-table-column label="基期" width="160">
              <template #default="{ row }">
                {{ row.base_period?.year }}年{{ row.base_period?.months?.join(',') }}月
              </template>
            </el-table-column>
            <el-table-column label="当期" width="160">
              <template #default="{ row }">
                {{ row.curr_period?.year }}年{{ row.curr_period?.months?.join(',') }}月
              </template>
            </el-table-column>
            <el-table-column label="保费阈值%" width="120">
              <template #default="{ row }">
                <el-input-number
                  v-model="row.thresholds.premium_drop_pct"
                  :min="-100"
                  :max="0"
                  :step="1"
                  size="small"
                  controls-position="right"
                  style="width: 110px"
                />
              </template>
            </el-table-column>
            <el-table-column label="单量阈值%" width="120">
              <template #default="{ row }">
                <el-input-number
                  v-model="row.thresholds.policies_drop_pct"
                  :min="-100"
                  :max="0"
                  :step="1"
                  size="small"
                  controls-position="right"
                  style="width: 110px"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80" fixed="right">
              <template #default="{ $index }">
                <el-button type="danger" text size="small" @click="removeRule($index)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="rule-actions">
            <el-button type="success" size="small" @click="addRule">
              + 新增规则
            </el-button>
            <el-button type="primary" size="small" :loading="savingRules" @click="saveRulesConfig">
              保存配置
            </el-button>
            <el-button size="small" :loading="savingRules" @click="resetRulesConfig">
              恢复默认
            </el-button>
          </div>
        </div>
    </div>

    <!-- 分析结果展示区 -->
    <div v-loading="analyzing" class="result-area">
      <!-- 空状态：未分析时显示 -->
      <el-empty v-if="!tables.length && !analyzing && !errorMsg" description="点击上方「开始分析」按钮进行规则异常分析" />

      <!-- 多表切换：横向铺开按钮（全部模板可见，一行放不下时自动换行） -->
      <div v-if="tables.length" class="result-tab-bar" role="tablist" aria-label="分析结果表切换">
        <div
          v-for="table in tables"
          :key="table.id"
          class="result-tab-btn"
          :class="{ active: table.id === activeTableId }"
          :data-tab-id="table.id"
          role="tab"
          :tabindex="table.id === activeTableId ? 0 : -1"
          :aria-selected="table.id === activeTableId ? 'true' : 'false'"
          @click="switchResultTable(table.id)"
          @keydown.enter.prevent="switchResultTable(table.id)"
          @keydown.space.prevent="switchResultTable(table.id)"
          @keydown.arrow-right.prevent="moveResultFocus(1)"
          @keydown.arrow-left.prevent="moveResultFocus(-1)"
          :title="table.name"
        >
          {{ table.name }}
        </div>
      </div>

      <!-- 当前激活表内容 -->
      <div v-for="table in tables" :key="table.id" v-show="table.id === activeTableId" class="result-table-pane">
          <!-- 摘要行 -->
          <el-alert
            type="info"
            :closable="false"
            show-icon
            class="summary-alert"
          >
            <template #title>
              共识别 <strong>{{ table.rows.length }}</strong> 家异常客户
            </template>
          </el-alert>

          <!-- 操作行：导出 CSV -->
          <div class="table-actions">
            <el-button size="small" @click="exportTableCsv(table)">导出 CSV</el-button>
          </div>

          <!-- 数据表格 -->
          <el-table
            :data="getPagedRows(table)"
            stripe
            border
            size="small"
            style="width: 100%"
          >
            <el-table-column
              v-for="col in table.columns"
              :key="col"
              :prop="col"
              :label="col"
              sortable
              min-width="120"
            >
              <template #default="{ row }">
                <!-- 风险等级列：el-tag 渲染 -->
                <template v-if="col === '风险等级'">
                  <el-tag :type="riskTagType(row[col])" size="small">
                    {{ row[col] }}
                  </el-tag>
                </template>
                <!-- 数值列：颜色标记 -->
                <template v-else-if="isPercentCol(col)">
                  <span :style="{ color: percentColor(row[col]) }">
                    {{ formatPercent(row[col]) }}
                  </span>
                </template>
                <!-- 普通列 -->
                <template v-else>
                  {{ row[col] }}
                </template>
              </template>
            </el-table-column>
          </el-table>

          <!-- 分页 -->
          <el-pagination
            v-if="table.rows.length > pageSize"
            class="table-pagination"
            :current-page="pageMap[table.id] || 1"
            :page-size="pageSize"
            :total="table.rows.length"
            layout="total, prev, pager, next"
            @current-change="(p) => onPageChange(table.id, p)"
          />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, watch, nextTick, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Calendar } from '@element-plus/icons-vue'

// ===================== Props =====================
const props = defineProps({
  sessionId: { type: String, default: '' },   // 会话 ID
  startMonth: { type: String, default: '' },  // "YYYY-MM" 格式
  endMonth: { type: String, default: '' },    // "YYYY-MM" 格式
})

// ===================== Mock 模式检测 =====================
const mockMode = import.meta.env.VITE_USE_MOCK === 'true'

// ===================== 状态管理 =====================
const analyzing = ref(false)       // 是否正在执行分析
const errorMsg = ref('')           // 错误信息
const tables = ref([])             // 分析结果表数组 [{id, name, columns, rows, summary}]
const activeTableId = ref('')      // 当前激活的表 Tab
const configCollapsed = ref(true)  // 规则配置面板折叠状态（备用）
const loadingRules = ref(false)    // 加载规则配置中
const savingRules = ref(false)     // 保存规则配置中
const rulesConfig = ref([])        // 规则配置列表
const pageSize = 50                // 每页行数
const pageMap = reactive({})       // 各表当前页码 { tableId: page }

// ===================== 工具函数 =====================

/** CSV 字段转义：处理逗号、引号、换行 */
function csvEscape(val) {
  if (val == null) return ''
  const s = String(val)
  if (s.includes(',') || s.includes('"') || s.includes('\n')) {
    return '"' + s.replace(/"/g, '""') + '"'
  }
  return s
}

/** 下载 CSV 文件（带 BOM，UTF-8 编码） */
function downloadCSV(filename, columns, rows) {
  const BOM = '\uFEFF'
  const header = columns.join(',')
  const body = rows.map(r => columns.map(c => csvEscape(r[c])).join(',')).join('\n')
  const blob = new Blob([BOM + header + '\n' + body], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** 判断是否为百分比列（保费环比%、单量环比%等） */
function isPercentCol(col) {
  return /环比|%/.test(col)
}

/** 百分比数值颜色：下降红色(#ff3b30)，上升绿色(#34c759) */
function percentColor(val) {
  if (val == null) return ''
  const num = parseFloat(val)
  if (isNaN(num)) return ''
  return num < 0 ? '#ff3b30' : num > 0 ? '#34c759' : ''
}

/** 格式化百分比显示 */
function formatPercent(val) {
  if (val == null) return '-'
  const num = parseFloat(val)
  if (isNaN(num)) return val
  return num.toFixed(2) + '%'
}

/** 风险等级对应 el-tag type：双降=danger, 保费降=warning, 单量降=info */
function riskTagType(level) {
  if (!level) return 'info'
  if (level.includes('双降')) return 'danger'
  if (level.includes('保费降')) return 'warning'
  if (level.includes('单量降')) return 'info'
  return 'info'
}

/** 获取分页后的行数据 */
function getPagedRows(table) {
  const page = pageMap[table.id] || 1
  const start = (page - 1) * pageSize
  return table.rows.slice(start, start + pageSize)
}

/** 分页页码变更处理 */
function onPageChange(tableId, page) {
  pageMap[tableId] = page
}

/** 切换到指定结果表（同步更新 roving tabindex 焦点语义） */
function switchResultTable(tableId) {
  activeTableId.value = tableId
}

/** 键盘方向键在结果表 Tab 间移动焦点（箭头键导航，仅移动焦点不切换） */
function moveResultFocus(step) {
  const idx = tables.value.findIndex((t) => t.id === activeTableId.value)
  const nextIdx = (idx + step + tables.value.length) % tables.value.length
  const nextId = tables.value[nextIdx]?.id
  if (!nextId) return
  // 更新 active 跟随焦点（结果区同步切换，交互更流畅）
  activeTableId.value = nextId
  const el = document.querySelector(`.result-tab-btn[data-tab-id="${nextId}"]`)
  el?.focus()
}

// ===================== Mock 数据生成 =====================

/** 生成 Mock 假数据（3 张表，每张 5 行） */
function generateMockData() {
  const riskLevels = ['双降', '保费降', '单量降']
  const mockTables = []
  const tableNames = ['按产品线分析', '按地区分析', '按客户等级分析']

  for (let t = 0; t < 3; t++) {
    const columns = ['客户名称', '风险等级', '基期保费', '当期保费', '保费环比%', '基期单量', '当期单量', '单量环比%']
    const rows = []
    for (let i = 0; i < 5; i++) {
      const basePremium = Math.floor(Math.random() * 100000) + 50000
      const curPremium = Math.floor(Math.random() * 100000) + 30000
      const baseCount = Math.floor(Math.random() * 200) + 50
      const curCount = Math.floor(Math.random() * 200) + 30
      rows.push({
        '客户名称': '客户' + String.fromCharCode(65 + t) + (i + 1),
        '风险等级': riskLevels[i % 3],
        '基期保费': basePremium,
        '当期保费': curPremium,
        '保费环比%': (((curPremium - basePremium) / basePremium) * 100).toFixed(2),
        '基期单量': baseCount,
        '当期单量': curCount,
        '单量环比%': (((curCount - baseCount) / baseCount) * 100).toFixed(2),
      })
    }
    mockTables.push({
      id: 'table_' + (t + 1),
      name: tableNames[t],
      columns,
      rows,
      summary: '共识别 ' + rows.length + ' 家异常客户',
    })
  }
  return mockTables
}

/** Mock 规则配置数据 */
function generateMockRules() {
  return [
    { name: '双降规则', base_month: props.startMonth || '2025-10', current_month: props.endMonth || '2026-07', threshold: 10 },
    { name: '保费下降规则', base_month: props.startMonth || '2025-10', current_month: props.endMonth || '2026-07', threshold: 20 },
    { name: '单量下降规则', base_month: props.startMonth || '2025-10', current_month: props.endMonth || '2026-07', threshold: 15 },
  ]
}

// ===================== API 调用 =====================

/** 获取规则配置 GET /api/anomaly/rules-config */
async function fetchRulesConfig() {
  if (mockMode) {
    rulesConfig.value = generateMockRules()
    return
  }
  loadingRules.value = true
  try {
    const resp = await fetch('/api/anomaly/rules-config')
    if (!resp.ok) throw new Error('HTTP ' + resp.status)
    const data = await resp.json()
    rulesConfig.value = data.tables || data.rules || []
  } catch (err) {
    console.error('[RuleAnomalyPanel] 获取规则配置失败:', err)
    ElMessage.error('获取规则配置失败：' + (err.message || '未知错误'))
  } finally {
    loadingRules.value = false
  }
}

/** 保存规则配置 PUT /api/anomaly/rules-config */
async function saveRulesConfig() {
  if (mockMode) {
    ElMessage.success('Mock 模式：配置已保存（模拟）')
    return
  }
  savingRules.value = true
  try {
    const resp = await fetch('/api/anomaly/rules-config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        version: '1.0',
        global: { min_policies: 2, drop_rate: 0.30, min_consecutive: 2, idle_months: 2 },
        tables: rulesConfig.value,
      }),
    })
    if (!resp.ok) throw new Error('HTTP ' + resp.status)
    ElMessage.success('规则配置已保存')
  } catch (err) {
    console.error('[RuleAnomalyPanel] 保存规则配置失败:', err)
    ElMessage.error('保存规则配置失败：' + (err.message || '未知错误'))
  } finally {
    savingRules.value = false
  }
}

/** 恢复默认规则配置 */
async function resetRulesConfig() {
  if (mockMode) {
    rulesConfig.value = generateMockRules()
    ElMessage.success('Mock 模式：已恢复默认配置')
    return
  }
  try {
    const resp = await fetch('/api/anomaly/rules-config/reset', { method: 'POST' })
    if (!resp.ok) throw new Error('HTTP ' + resp.status)
    await fetchRulesConfig()
    ElMessage.success('已恢复默认规则配置')
  } catch (err) {
    console.error('[RuleAnomalyPanel] 恢复默认配置失败:', err)
    ElMessage.error('恢复默认配置失败：' + (err.message || '未知错误'))
  }
}

/** 新增一条空规则 */
function addRule() {
  rulesConfig.value.push({
    id: 'custom_' + Date.now(),
    name: '新规则',
    enabled: true,
    type: 'period_compare',
    base_period: { year: 2026, months: [1, 2, 3] },
    curr_period: { year: 2026, months: [4, 5, 6] },
    thresholds: { premium_drop_pct: -30, policies_drop_pct: -30 },
    output_columns: [],
    sort_by: { field: 'premium_change_pct', order: 'asc' },
  })
  ElMessage.success('已添加新规则，请在表格中编辑')
}

/** 删除指定规则 */
function removeRule(index) {
  if (rulesConfig.value.length <= 1) {
    ElMessage.warning('至少保留一条规则')
    return
  }
  rulesConfig.value.splice(index, 1)
  ElMessage.success('规则已删除（需保存配置才生效）')
}

/** 执行规则分析 POST /api/anomaly/rules-analyze */
async function runAnalysis() {
  if (!props.sessionId) {
    ElMessage.error('缺少会话信息，请重新上传文件')
    return
  }
  errorMsg.value = ''
  tables.value = []
  activeTableId.value = ''
  analyzing.value = true

  try {
    if (mockMode) {
      // Mock 模式：延迟后返回假数据
      await new Promise(r => setTimeout(r, 800))
      tables.value = generateMockData()
      activeTableId.value = tables.value[0]?.id || ''
      nextTick(() => {
        if (tables.value[0]) {
          document.querySelector(`.result-tab-btn[data-tab-id="${tables.value[0].id}"]`)?.focus()
        }
      })
      ElMessage.success('Mock 模式：分析完成（模拟数据）')
      return
    }

    const resp = await fetch('/api/anomaly/rules-analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: props.sessionId }),
    })

    if (!resp.ok) {
      if (resp.status === 404) {
        errorMsg.value = '会话不存在或已过期，请重新上传文件'
      } else {
        const errData = await resp.json().catch(() => ({}))
        errorMsg.value = errData.detail || '分析请求失败（HTTP ' + resp.status + '）'
      }
      return
    }

    const data = await resp.json()
    tables.value = data.tables || []
    if (tables.value.length) {
      activeTableId.value = tables.value[0].id
      // 分析完成后将焦点移到首个结果 Tab，方便键盘继续操作
      nextTick(() => {
        document.querySelector(`.result-tab-btn[data-tab-id="${tables.value[0].id}"]`)?.focus()
      })
    }
    ElMessage.success('规则分析完成，共生成 ' + tables.value.length + ' 张规则表')
  } catch (err) {
    console.error('[RuleAnomalyPanel] 规则分析失败:', err)
    errorMsg.value = '网络错误：' + (err.message || String(err))
  } finally {
    analyzing.value = false
  }
}

/** 导出单表 CSV */
function exportTableCsv(table) {
  if (!table || !table.rows.length) {
    ElMessage.warning('表格数据为空，无法导出')
    return
  }
  const safeName = (table.name || table.id).replace(/[\\/:*?"<>|]/g, '_').slice(0, 50)
  const filename = safeName + '_规则分析.csv'
  downloadCSV(filename, table.columns, table.rows)
  ElMessage.success('CSV 已开始下载：' + filename)
}

/** 导出全部 Excel（合并所有表到一个 CSV 下载） */
function exportAllExcel() {
  if (!tables.value.length) {
    ElMessage.warning('暂无分析结果可导出')
    return
  }
  // 将所有表合并为一个 CSV，用空行分隔
  const BOM = '\uFEFF'
  const parts = []
  for (const table of tables.value) {
    parts.push('【' + table.name + '】')
    parts.push(table.columns.join(','))
    for (const row of table.rows) {
      parts.push(table.columns.map(c => csvEscape(row[c])).join(','))
    }
    parts.push('') // 表间空行
  }
  const blob = new Blob([BOM + parts.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = '规则异常分析_全部.csv'
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('全部结果已开始下载')
}

// ===================== 生命周期 =====================

/** 当前分析范围文案（来自业绩分析筛选） */
const rangeText = computed(() => {
  if (!props.startMonth && !props.endMonth) return ''
  return `${props.startMonth || '-'} ~ ${props.endMonth || '-'}`
})

// 首次进入自动执行规则分析（有会话时），减少一次手动点击；可随时用按钮重跑
onMounted(() => {
  if (props.sessionId) {
    runAnalysis()
  }
})

// 监听配置面板展开时自动加载规则配置
watch(configCollapsed, (val) => {
  if (!val && !rulesConfig.value.length) {
    fetchRulesConfig()
  }
})
</script>

<style scoped>
.rule-anomaly-panel {
  font-size: var(--fs-base);
}
.rule-anomaly-panel .action-bar {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);
  flex-wrap: wrap;
}

/* 分析范围提示条 */
.range-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: var(--fs-sm);
  color: var(--color-text-secondary);
  background: var(--bg-hover);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  margin-bottom: var(--spacing-md);
}
.range-bar .el-icon {
  color: var(--color-primary);
}
.range-bar .range-hint {
  color: var(--color-text-muted);
}
.rule-anomaly-panel .rule-config-collapse {
  margin-bottom: var(--spacing-md);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.rule-anomaly-panel .rule-config-body {
  padding: var(--spacing-md);
}
.rule-anomaly-panel .result-area {
  min-height: 200px;
}

/* ---- 结果表切换按钮（横向铺开） ---- */
.result-tab-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: var(--spacing-md);
}
.result-tab-btn {
  display: inline-flex;
  align-items: center;
  padding: 0 16px;
  height: 40px;
  border-radius: 6px;
  border: 1px solid #e0e0e0;
  background: #f5f5f7;
  color: #6e6e73;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
  user-select: none;
}
.result-tab-btn:hover {
  background: #e8e8ed;
}
.result-tab-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
.result-tab-btn.active {
  background: #0066cc;
  color: #fff;
  border-color: #0066cc;
  font-weight: 600;
}
.rule-anomaly-panel .summary-alert {
  margin-bottom: var(--spacing-sm);
}
.rule-anomaly-panel .table-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: var(--spacing-sm);
}
.rule-anomaly-panel .table-pagination {
  margin-top: var(--spacing-md);
  display: flex;
  justify-content: flex-end;
}
</style>
