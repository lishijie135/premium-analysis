/**
 * PDF 导出工具：使用 jsPDF + autoTable 生成真正的 PDF 表格（文字可选中复制）。
 * 
 * 中文支持策略：
 * 1. 尝试从 CDN 加载 Noto Sans SC 字体（约 4MB）
 * 2. 若加载失败，回退到浏览器 print-to-PDF（原生支持中文）
 */
import { ElMessage } from 'element-plus'
import jsPDF from 'jspdf'
import 'jspdf-autotable'
import { marked } from 'marked'

// Google Fonts CDN - Noto Sans SC Regular
const FONT_URL = 'https://fonts.gstatic.com/s/notosanssc/v36/k3kCo84MPvpLmixcA63oeAL7Iqp5IZJF9bmaG9_FnYg.woff2'

let cachedFontBase64 = null

/**
 * 异步加载字体并转为 base64
 */
async function loadChineseFont() {
  if (cachedFontBase64) return cachedFontBase64
  
  try {
    const resp = await fetch(FONT_URL)
    if (!resp.ok) throw new Error('Font fetch failed')
    const buffer = await resp.arrayBuffer()
    const bytes = new Uint8Array(buffer)
    
    // 转 base64
    let binary = ''
    for (let i = 0; i < bytes.length; i++) {
      binary += String.fromCharCode(bytes[i])
    }
    cachedFontBase64 = btoa(binary)
    return cachedFontBase64
  } catch (err) {
    console.warn('[PDF] 字体加载失败，将回退到浏览器打印:', err)
    return null
  }
}

/**
 * 解析 Markdown 文本，提取结构化内容（段落、标题、表格）
 */
function parseMarkdown(md) {
  const lines = md.split('\n')
  const blocks = []
  let currentParagraph = []
  
  const flushParagraph = () => {
    if (currentParagraph.length > 0) {
      blocks.push({ type: 'text', content: currentParagraph.join('\n') })
      currentParagraph = []
    }
  }
  
  const isTableSep = (line) => /^\|?[\s:|-]+\|?$/.test(line.trim()) && line.includes('-')
  
  let i = 0
  while (i < lines.length) {
    const line = lines[i].trim()
    
    // 检测表格开始
    if (line.startsWith('|') && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      flushParagraph()
      
      // 收集表格行
      const headerLine = line
      i++ // skip separator
      const dataRows = []
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        dataRows.push(lines[i].trim())
        i++
      }
      
      // 解析表头
      const headers = headerLine.split('|').filter(c => c.trim()).map(c => c.trim())
      // 解析数据行
      const rows = dataRows.map(row => 
        row.split('|').filter(c => c.trim()).map(c => c.trim())
      )
      
      blocks.push({ type: 'table', headers, rows })
      continue
    }
    
    // 普通行
    if (line) {
      currentParagraph.push(line)
    } else {
      flushParagraph()
    }
    i++
  }
  flushParagraph()
  
  return blocks
}

/**
 * 将 Markdown 内容导出为 PDF
 * @param {string} markdownText - 原始 Markdown 文本
 * @param {string} title - PDF 标题
 * @returns {Promise<boolean>} - 是否成功
 */
export async function exportMarkdownToPDF(markdownText, title = '分析报告') {
  if (!markdownText || !markdownText.trim()) {
    ElMessage.warning('暂无内容可导出')
    return false
  }
  
  // 先尝试加载字体
  const fontBase64 = await loadChineseFont()
  
  // 如果字体加载失败，回退到浏览器打印
  if (!fontBase64) {
    ElMessage.info('正在使用浏览器打印模式导出 PDF...')
    fallbackToBrowserPrint(markdownText, title)
    return true
  }
  
  try {
    const doc = new jsPDF({
      orientation: 'portrait',
      unit: 'mm',
      format: 'a4',
    })
    
    // 添加中文字体
    doc.addFileToVFS('NotoSansSC-Regular.ttf', fontBase64)
    doc.addFont('NotoSansSC-Regular.ttf', 'NotoSansSC', 'normal')
    doc.setFont('NotoSansSC')
    
    const pageWidth = doc.internal.pageSize.getWidth()
    const margin = 15
    const contentWidth = pageWidth - 2 * margin
    let y = margin
    
    // 标题
    doc.setFontSize(18)
    doc.text(title, margin, y)
    y += 10
    
    // 生成时间
    doc.setFontSize(10)
    doc.setTextColor(150, 150, 150)
    doc.text(`生成时间：${new Date().toLocaleString('zh-CN')}`, margin, y)
    y += 10
    doc.setTextColor(0, 0, 0)
    
    // 分隔线
    doc.setDrawColor(200, 200, 200)
    doc.line(margin, y, pageWidth - margin, y)
    y += 8
    
    // 解析 Markdown
    const blocks = parseMarkdown(markdownText)
    
    doc.setFontSize(11)
    const lineHeight = 6
    
    for (const block of blocks) {
      // 检查是否需要换页
      if (y > 270) {
        doc.addPage()
        y = margin
      }
      
      if (block.type === 'text') {
        // 处理文本块（可能包含 # 标题标记）
        const lines = block.content.split('\n')
        for (const line of lines) {
          if (y > 270) {
            doc.addPage()
            y = margin
          }
          
          // 检测 Markdown 标题
          const headingMatch = line.match(/^(#{1,3})\s+(.+)$/)
          if (headingMatch) {
            const level = headingMatch[1].length
            const text = headingMatch[2]
            
            if (level === 1) {
              doc.setFontSize(16)
              doc.setFont('NotoSansSC', 'bold')
              y += 4
            } else if (level === 2) {
              doc.setFontSize(14)
              doc.setFont('NotoSansSC', 'bold')
              y += 3
            } else {
              doc.setFontSize(12)
              doc.setFont('NotoSansSC', 'bold')
              y += 2
            }
            
            doc.text(text, margin, y)
            y += lineHeight + 2
            doc.setFontSize(11)
            doc.setFont('NotoSansSC', 'normal')
          } else {
            // 普通文本，自动换行
            const splitText = doc.splitTextToSize(line, contentWidth)
            for (const t of splitText) {
              if (y > 270) {
                doc.addPage()
                y = margin
              }
              doc.text(t, margin, y)
              y += lineHeight
            }
          }
        }
        y += 4
      } else if (block.type === 'table') {
        // 使用 autoTable 渲染表格
        doc.autoTable({
          head: [block.headers],
          body: block.rows,
          startY: y,
          margin: { left: margin, right: margin },
          styles: {
            font: 'NotoSansSC',
            fontSize: 9,
            cellPadding: 3,
            textColor: [30, 30, 30],
          },
          headStyles: {
            fillColor: [24, 115, 232],
            textColor: [255, 255, 255],
            fontStyle: 'bold',
            fontSize: 9,
          },
          alternateRowStyles: {
            fillColor: [248, 249, 250],
          },
          theme: 'grid',
        })
        
        y = doc.lastAutoTable.finalY + 8
      }
    }
    
    // 保存 PDF
    const filename = `${title}_${new Date().toISOString().slice(0, 10)}.pdf`
    doc.save(filename)
    ElMessage.success(`PDF 已下载：${filename}`)
    return true
  } catch (err) {
    console.error('[PDF] jsPDF 导出失败:', err)
    ElMessage.warning('PDF 生成失败，切换到浏览器打印模式...')
    fallbackToBrowserPrint(markdownText, title)
    return true
  }
}

/**
 * 回退方案：使用浏览器 print-to-PDF
 */
function fallbackToBrowserPrint(markdownText, title) {
  const htmlContent = marked.parse(markdownText)
    
    const printWindow = window.open('', '_blank')
    if (!printWindow) {
      ElMessage.error('请允许弹出窗口以导出 PDF')
      return
    }
    
    const html = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>${title}</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;font-size:14px;line-height:1.6;color:#202124;padding:20px;max-width:900px;margin:0 auto;-webkit-print-color-adjust:exact;print-color-adjust:exact}
h1,h2,h3{color:#1a73e8;margin:16px 0 8px}
h1{font-size:20px;border-bottom:2px solid #1a73e8;padding-bottom:8px}
h2{font-size:16px}
h3{font-size:14px}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13px;page-break-inside:avoid}
th{background:#1873e8;color:#fff;padding:8px 10px;font-weight:600;border:1px solid #dadce0;text-align:left}
td{padding:6px 10px;border:1px solid #dadce0}
tr:nth-child(even){background:#f8f9fa}
p{margin:8px 0}
ul,ol{margin:8px 0;padding-left:24px}
li{margin:4px 0}
code{background:#f1f3f4;padding:2px 6px;border-radius:3px;font-size:13px}
pre{background:#f6f8fa;padding:12px;border-radius:6px;overflow-x:auto;margin:8px 0}
blockquote{border-left:3px solid #1a73e8;padding-left:12px;color:#5f6368;margin:12px 0}
hr{border:none;border-top:1px solid #e8eaed;margin:16px 0}
@media print{
  body{padding:10px}
  table{page-break-inside:avoid}
  tr{page-break-inside:avoid}
}
</style></head><body>
<h1>${title}</h1>
<p style="color:#9aa0a6;font-size:12px">生成时间：${new Date().toLocaleString('zh-CN')}</p>
<hr>
${htmlContent}
</body></html>`
    
    printWindow.document.write(html)
    printWindow.document.close()
    setTimeout(() => {
      printWindow.print()
      // 不自动关闭，让用户手动操作
    }, 500)
    ElMessage.success('请在打印对话框中选择"另存为 PDF"')
}
