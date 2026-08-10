# 停止旧进程
Get-Process -Name python -ErrorAction SilentlyContinue | ForEach-Object {
    $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    if ($cmdline -like '*premium-analysis*' -or $cmdline -like '*uvicorn*') {
        Stop-Process -Id $_.Id -Force
    }
}

# 启动后端服务（端口 8000）
cd D:\joe-project\workspace\premium-analysis\backend
$env:PYTHONPATH = "D:\joe-project\workspace\premium-analysis\backend"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 关键参数说明：
--reload：代码修改后自动热重载，开发阶段无需手动重启
--host 0.0.0.0：允许外部访问
--port 8000：后端端口

