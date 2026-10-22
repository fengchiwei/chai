@echo off
rem Double-click to start Anla Youth locally. Logic lives in scripts\start.ps1.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
if errorlevel 1 (
  echo.
  echo Startup failed. See the messages above.
  pause
)
