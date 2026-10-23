# 本機啟動（只監聽 127.0.0.1）。金鑰與後台密碼請先在同一個 PowerShell 視窗設定，不要寫進檔案。
# 用法（在專案根目錄）：powershell -ExecutionPolicy Bypass -File .\scripts\run_local.ps1 [-Port 5002]
param([int]$Port = 5000)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
if (-not $env:WORKBENCH_PASSWORD) { Write-Host "提醒：未設定 WORKBENCH_PASSWORD，後台與 /explain 會停用。" }
if (-not $env:LLM_API_KEY -and -not $env:GEMINI_API_KEY -and -not $env:OPENAI_API_KEY -and -not $env:ANTHROPIC_API_KEY) {
    Write-Host "提醒：未設定模型金鑰（LLM_API_KEY），將使用本機備援回覆。"
}
# 預設只給本機；要讓同一網路的手機連入，先設定 $env:HOST = "0.0.0.0"（正式使用請改 HTTPS）。
$listen = if ($env:HOST) { $env:HOST } else { "127.0.0.1" }
& $python -c "from app import app; app.run(host='$listen', port=$Port, debug=False, use_reloader=False)"
