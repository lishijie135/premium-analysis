/** CSV 导出工具：纯前端 Blob 下载，UTF-8 + BOM，逗号分隔，含转义 */

function escapeCell(value) {
  if (value === null || value === undefined) return ''
  const s = String(value)
  // 包含逗号、引号、换行时用双引号包裹，内部引号转义为两个引号
  return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}

export function toCsv(headers, rows) {
  const lines = [headers.map(escapeCell).join(',')]
  for (const row of rows) {
    lines.push(row.map(escapeCell).join(','))
  }
  return lines.join('\r\n')
}

/**
 * 下载 CSV 文件
 * @param {string} filename 文件名，如 异常客户_保费逐月下降.csv
 * @param {string[]} headers 表头（中文列名）
 * @param {Array<Array>} rows 数据行
 */
export function downloadCsv(filename, headers, rows) {
  const content = '\ufeff' + toCsv(headers, rows) // BOM 保证 Excel 识别 UTF-8
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
