/** 数字与百分比格式化工具 */

export function fmtNum(value, digits = 0) {
  if (value === null || value === undefined || value === '') return '-'
  const n = Number(value)
  if (Number.isNaN(n)) return '-'
  return n.toLocaleString('zh-CN', { maximumFractionDigits: digits })
}

/** 保费金额：保留 1 位小数 */
export function fmtMoney(value) {
  return fmtNum(value, 1)
}

/** 百分比：正数加号，null 显示 - */
export function fmtPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-'
  const n = Number(value)
  return (n > 0 ? '+' : '') + n.toFixed(1) + '%'
}

/** 涨跌颜色 class：正绿负红 */
export function pctClass(value) {
  if (value === null || value === undefined) return ''
  const n = Number(value)
  if (n > 0) return 'val-up'
  if (n < 0) return 'val-down'
  return ''
}

/** H 类 monthly_growth 的中文展示 */
export function growthText(flag) {
  if (flag === true) return '逐月增长'
  if (flag === false) return '非逐月增长'
  return '数据不足'
}
