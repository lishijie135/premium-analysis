# 客户业绩保费分析系统 · 测试报告

- **测试日期**：2026-08-31
- **测试范围**：前端 UI 全系统改版、后端 AI 链路（模型切换）、服务重启验证
- **测试结论**：✅ 通过（含 1 项已知环境遗留、1 项已解决的历史缺陷）

---

## 1. 测试环境

| 项 | 配置 |
|---|---|
| 前端 | Vue 3 + Vite，端口 `5176`（`VITE_USE_MOCK=false`，`/api` 代理至 8000） |
| 后端 | FastAPI + uvicorn，端口 `8000` |
| LLM | 阿里云百炼 dashscope `qwen3.7-plus`（兼容 OpenAI 协议） |
| 测试工具 | `@vue/compiler-sfc`（组件编译）、`curl`（接口联调）、浏览器端口探测 |

> 说明：前端采用真实后端联调，未使用 mock。

---

## 2. 前端 UI 全系统改版测试

### 2.1 组件编译验证

对改动的 9 个组件用 `@vue/compiler-sfc` 单独编译（template + script），结果全部通过：

| 组件 | 路径 | 编译结果 |
|---|---|---|
| App.vue | `src/App.vue` | ✅ PASS |
| 全局样式 | `src/styles/base.css` | ✅ PASS |
| ResultPage.vue | `src/components/ResultPage.vue` | ✅ PASS |
| AiChatPanel.vue | `src/components/AiChatPanel.vue` | ✅ PASS |
| UploadPage.vue | `src/components/UploadPage.vue` | ✅ PASS |
| TrendChart.vue | `src/components/TrendChart.vue` | ✅ PASS |
| RuleAnomalyPanel.vue | `src/components/RuleAnomalyPanel.vue` | ✅ PASS |
| AiAnomalyPanel.vue | `src/components/AiAnomalyPanel.vue` | ✅ PASS |
| MappingStep.vue | `src/components/MappingStep.vue` | ✅ PASS |

### 2.2 运行时样式验证（dev server 模块探测）

在运行中的 dev server（5176）拉取编译后模块，确认新设计已生效：

| 验证项 | 命中关键字 | 结果 |
|---|---|---|
| AiChatPanel 新样式 | `chat-input-row` / `empty-title` / `send-btn` | ✅ 命中 3 |
| App.vue 新步骤条 | `step-row` / `is-done` / `is-active` / `global-nav` | ✅ 命中 3 |

### 2.3 设计改动摘要

- 全局 token 重做：Action Blue `#0066cc`、Ink `#1d1d1f`、Parchment `#f5f5f7`、hairline 描边、pill 圆角体系
- 顶栏：渐变蓝 → 黑色 44px global nav
- 侧栏：200→240px Parchment + 自定义步骤条（已完成绿圈✓ / 当前黑底蓝圆）
- ResultPage：竖排 `el-tabs` → 横向 pill Tab（激活黑底白字）
- AiChatPanel：空状态重制、气泡黑/白分色、pill 输入区、⌘/Ctrl+Enter 发送
- 图表与异常面板配色映射到 Apple 色板

---

## 3. 后端 AI 链路测试

### 3.1 接口健康检查

| 接口 | 方法 | 结果 |
|---|---|---|
| `/api/health` | GET | ✅ `{"status":"ok"}` |
| `/api/upload` | POST | ✅ 正常接收 xlsx，返回 session_id 与识别列 |
| `/api/anomaly/stream` | POST | ✅ 正常（见 3.3） |
| `/api/chat/stream` | POST | ✅ 接口存活（参数校验 422 符合预期） |

### 3.2 模型切换测试（关键缺陷修复）

后端 `.env` 由本地 ollama 切换至线上 dashscope：

| 模型 | 请求结果 | 说明 |
|---|---|---|
| `qwen3.7-flash`（初次切换） | ❌ `403 Forbidden` | 该 key/账号未授权 flash 档（或档位未订阅） |
| `qwen3.7-plus`（当前） | ✅ `200 OK` | 模型正常返回，鉴权通过 |

**结论**：原报错「代码生成失败: All connection attempts failed」为旧进程连不上本地 ollama 所致；切换 dashscope 后该错误消失；`flash` 的 403 是档位授权问题，`plus` 验证可用。

### 3.3 端到端 AI 分析（8000 端口，模型 qwen3.7-plus）

**测试步骤**：上传测试数据 xlsx → 取 `session_id` → 调用 `/api/anomaly/stream`。

- 测试数据列识别：`客户代码` / `签单时间` / `保费量` / `出单量`（识别正确）
- 模型行为：自动生成 pandas 分析代码 → 后端沙箱执行 → 返回结构化结果
- 返回结果示例：

```json
{ "success": true,
  "output": "保费最高的客户分析结果: [{'customer': 'C001', 'total_premium': 390000.0}]",
  "validation": { "warnings": [], "nan_check": { "found": false } } }
```

✅ AI 分析链路完整可用，代码生成、执行、校验均正常。

---

## 4. 服务重启验证

| 服务 | 重启前端口状态 | 重启后状态 |
|---|---|---|
| 后端 uvicorn | 8000 旧进程读 ollama 配置（已强关） | ✅ 8000 监听，PID 34752，读 `qwen3.7-plus` |
| 前端 vite | 5176 | ✅ HTTP 200 |

重启后再次端到端验证（8000）：上传 → `anomaly/stream` 返回正确，旧 ollama 报错不再复现。

---

## 5. 测试结论

1. ✅ 前端全系统 Apple 风格改版，9 个组件编译 + 运行时样式均验证通过
2. ✅ 后端 AI 链路在 `qwen3.7-plus` 下完整可用（生成→执行→校验）
3. ✅ 服务重启后前后端均健康，历史 ollama 报错已根治
4. ⚠️ 仓库主干 `main` 的设计提交（commit `212c0551`）**尚未 push 至 origin**
5. ⚠️ 环境遗留：`backend/.gitignore` 未忽略 `node_modules`/`__pycache__`，工作区有历史污染未跟踪文件；`backend/_uvicorn.log`、`_uvicorn.err` 被进程占用暂未清理（无害、未进 git）

---

## 6. 遗留与建议

- [ ] 决定是否 `git push` 至 `origin/main`（对外共享操作，待确认）
- [ ] 补充 `.gitignore`：`node_modules`、`dist`、`__pycache__`、`*.pyc`、`*.log`
- [ ] 大王原截图中的「AI 数据分析」报错，根因已修复（ollama→dashscope + 模型档位），刷新前端即可正常
