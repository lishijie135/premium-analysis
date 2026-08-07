# 启动后端服务（端口 8000）
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
