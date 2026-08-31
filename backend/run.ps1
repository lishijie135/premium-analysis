# ============================================================
# One-click startup for backend + frontend services
# Backend: http://localhost:8000
# Frontend: http://localhost:5176
# start shell
# powershell -ExecutionPolicy Bypass -File "D:\joe-project\workspace\premium-analysis\backend\run.ps1"
# ============================================================

$ROOT = "D:\joe-project\workspace\premium-analysis"

# ---- Step 1: Stop old processes ----
Write-Host "[1/4] Stopping old processes..." -ForegroundColor Cyan
Get-Process -Name python -ErrorAction SilentlyContinue | ForEach-Object {
    $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    if ($cmdline -like '*premium-analysis*' -or $cmdline -like '*uvicorn*') {
        Write-Host "  Stopped Python PID=$($_.Id)" -ForegroundColor Yellow
        Stop-Process -Id $_.Id -Force
    }
}
Get-Process -Name node -ErrorAction SilentlyContinue | ForEach-Object {
    $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    if ($cmdline -like '*vite*' -or $cmdline -like '*premium-analysis*') {
        Write-Host "  Stopped Node PID=$($_.Id)" -ForegroundColor Yellow
        Stop-Process -Id $_.Id -Force
    }
}
Start-Sleep -Seconds 1

# ---- Step 2: Start backend (uvicorn, port 8000) ----
Write-Host "[2/4] Starting backend (http://localhost:8000)..." -ForegroundColor Cyan
$env:PYTHONPATH = "$ROOT\backend"
Start-Process -FilePath "python" -ArgumentList "-m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload" `
    -WorkingDirectory "$ROOT\backend" `
    -WindowStyle Normal

# Wait for backend ready (max 30s)
Write-Host "  Waiting for backend..." -ForegroundColor Gray
$backendReady = $false
Start-Sleep -Seconds 5
for ($i = 0; $i -lt 25; $i++) {
    $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        Write-Host "  Backend ready" -ForegroundColor Green
        $backendReady = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $backendReady) {
    Write-Host "  WARNING: Backend not ready in time" -ForegroundColor Yellow
}

# ---- Step 3: Start frontend (vite, port 5176) ----
Write-Host "[3/4] Starting frontend (http://localhost:5176)..." -ForegroundColor Cyan
Start-Process -FilePath "cmd.exe" -ArgumentList "/c cd /d `"$ROOT\frontend`" && npx vite --port 5176" `
    -WindowStyle Normal

# Wait for frontend ready (max 20s)
Write-Host "  Waiting for frontend..." -ForegroundColor Gray
$frontendReady = $false
Start-Sleep -Seconds 3
for ($i = 0; $i -lt 17; $i++) {
    $listener = Get-NetTCPConnection -LocalPort 5176 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        Write-Host "  Frontend ready" -ForegroundColor Green
        $frontendReady = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $frontendReady) {
    Write-Host "  WARNING: Frontend not ready in time" -ForegroundColor Yellow
}

# ---- Step 4: Done ----
Write-Host ""
Write-Host "[4/4] All services started!" -ForegroundColor Green
Write-Host "  Backend:  http://localhost:8000" -ForegroundColor White
Write-Host "  Frontend: http://localhost:5176" -ForegroundColor White
Write-Host ""
Write-Host "Press Ctrl+C to stop this script (services keep running in background)" -ForegroundColor DarkGray
