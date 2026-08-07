# 客户业绩保费分析系统

上传固定四列（签单时间、客户代码、保费量、出单量）的 Excel，仅当次在内存中分析，
输出全量业绩统计（月/季/年序列、年度对比）与八类异常/增长清单（A~H）。数据不落盘。

## 目录结构

```
premium-analysis\
├─ backend\     FastAPI 后端（端口 8000）
└─ frontend\    前端（Vite + React，端口 5173）
```

## 一、后端

### 环境要求
- Python 3.9+（注意：类型注解兼容 3.9 语法）
- 依赖：`backend\requirements.txt`

### 启动步骤
```powershell
cd D:\joe-project\workspace\premium-analysis\backend
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
# 方式一：脚本启动
.\run.ps1
# 方式二：命令启动
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
健康检查：浏览器访问 `http://localhost:8000/api/health`，返回 `{"status":"ok"}`。
交互式文档：`http://localhost:8000/docs`。

### 测试步骤（后端）
```powershell
cd D:\joe-project\workspace\premium-analysis\backend
# 生成埋点测试数据（可选，输出 backend\test_data\sample.xlsx）
python tools\gen_test_data.py
# 运行全部测试
python -m pytest tests -v
```

### API 摘要（全局前缀 /api）
| 接口 | 方法 | 说明 |
| --- | --- | --- |
| /api/upload | POST | multipart 上传 Excel（字段名 file），返回 session_id、列清单、预览、自动列映射 |
| /api/analyze | POST | 传 session_id + mapping，返回 summary/performance/anomalies/growth |
| /api/health | GET | 健康检查 |

会话仅存内存：TTL 30 分钟、最多 10 个、进程重启失效。

## 二、前端

### 启动步骤
```powershell
cd D:\joe-project\workspace\premium-analysis\frontend
npm install
npm run dev
```
访问 `http://localhost:5173`。

### 测试步骤（前端）
```powershell
cd D:\joe-project\workspace\premium-analysis\frontend
npm run build   # 构建验证（TypeScript 类型检查）
```

### 联调说明
- 前端 mock 开关为环境变量 `VITE_USE_MOCK`（默认 true）；
  联调时在 `frontend\.env.local` 中设置 `VITE_USE_MOCK=false` 后重启 dev server。
- 后端 CORS 已允许 `http://localhost:5173` 与 `http://localhost:5174`。
