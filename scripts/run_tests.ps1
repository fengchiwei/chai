# 執行完整測試套件；資料庫寫到暫存檔，不會在專案目錄留下 anla_youth.db。
# 用法（在專案根目錄）：powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$env:DATABASE_PATH = Join-Path $env:TEMP ("anla-test-" + [guid]::NewGuid().ToString() + ".db")
$env:LLM_PROVIDER = "builtin"
$env:PYTHONIOENCODING = "utf-8"
try {
    & $python -m unittest discover -s tests -p "test_*.py" -v
    $code = $LASTEXITCODE
} finally {
    Remove-Item $env:DATABASE_PATH -ErrorAction SilentlyContinue
}
exit $code
