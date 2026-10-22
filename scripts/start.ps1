# 一鍵啟動（由 start.bat 呼叫）。密碼與金鑰只存在這個視窗的記憶體，不寫入任何檔案。
# 參數：-Port 5002 改埠號；-NoBrowser 不自動開瀏覽器。已設定的環境變數不會再詢問。
param([int]$Port = 5000, [switch]$NoBrowser)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Read-Secret($prompt) {
    $secure = Read-Host $prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

Write-Host "=== 少年仔、安啦會客室 本機啟動 ===" -ForegroundColor Cyan

# 第一次使用：建立虛擬環境並安裝套件
$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "第一次啟動，正在建立虛擬環境並安裝套件……"
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "找不到 Python，請先安裝 Python 3.10 以上並勾選 Add to PATH。" }
    & $python -m pip install -q -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "套件安裝失敗，請確認網路連線。" }
}

if (-not $env:WORKBENCH_PASSWORD) {
    $env:WORKBENCH_PASSWORD = Read-Secret "設定後台密碼（直接按 Enter 跳過，後台將停用）"
}
if (-not $env:LLM_PROVIDER) {
    $key = Read-Secret "貼上 Gemini API 金鑰（直接按 Enter 使用本機備援回覆）"
    if ($key) {
        $env:GEMINI_API_KEY = $key
        $env:LLM_PROVIDER = "gemini"
        if (-not $env:GEMINI_MODEL) { $env:GEMINI_MODEL = "gemini-2.5-flash" }
    } else {
        $env:LLM_PROVIDER = "builtin"
    }
    Remove-Variable key
}

$url = "http://127.0.0.1:$Port/"
Write-Host ""
Write-Host "學生頁：$url"
Write-Host ("後台：  ${url}login" + $(if ($env:WORKBENCH_PASSWORD) { "" } else { "（未設密碼，已停用）" }))
Write-Host ("模型：  " + $(if ($env:LLM_PROVIDER -eq "builtin") { "本機備援回覆" } else { "$env:LLM_PROVIDER ($env:GEMINI_MODEL)" }))
Write-Host "停止伺服器：按 Ctrl+C 或關閉這個視窗" -ForegroundColor Yellow
Write-Host ""

if (-not $NoBrowser) {
    # 等伺服器回應後再開瀏覽器，最多等 20 秒
    Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile", "-Command", @"
for (`$i = 0; `$i -lt 40; `$i++) {
  try { Invoke-WebRequest -UseBasicParsing '${url}health' -TimeoutSec 1 | Out-Null; Start-Process '$url'; break } catch { Start-Sleep -Milliseconds 500 }
}
"@
}

& $python -c "from app import app; app.run(host='127.0.0.1', port=$Port, debug=False, use_reloader=False)"
exit $LASTEXITCODE
