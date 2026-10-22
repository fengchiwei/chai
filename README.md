# 少年仔、安啦會客室：Flask 本機原型

目前原始碼版本：**v1.3-B（含 v1.3-A.2 情境一致性修正）**。版本變更見 [docs/CHANGELOG.md](docs/CHANGELOG.md)，完整交接背景見 [docs/PROJECT_STATUS_20261021.md](docs/PROJECT_STATUS_20261021.md)。

提供學生對話、語音輸入／朗讀、南投資源、模擬案例測試、可解釋重播，以及需密碼登入的真人覆核工作臺。

**用途界線**：本原型沒有接入學校、公部門、警消或電郵發送服務。它不會替任何人撥號、寄信或通報。分流規則及模型會犯錯，不能取代受訓人員的評估或正式危機處理流程。正式供青少年使用前，需另作專業審查、資料保護、身分認證、監控及部署。

## 專案結構

```
anla-youth-v1.3-A.1/
├─ app.py                 Flask 路由（學生頁、工作臺、/demo、/explain、API）
├─ config.py              環境變數設定（模型、金鑰、後台密碼、資料庫路徑）
├─ requirements.txt
├─ engine/                對話與安全邏輯
│  ├─ triage.py, rules.py, bsrs5.py     四級分流、危機規則、BSRS-5
│  ├─ dialogue_policy.py                對話決策（薩提爾冰山、安全優先）
│  ├─ dialogue_ai.py                    模型呼叫、提示詞、兩階段流程
│  ├─ dialogue_reply.py                 本機備援回覆、送出前規則檢查
│  ├─ dialogue_role.py, support.py      陪伴角色、支持提議時機
│  ├─ referral.py, ai_agent.py          同意分享、摘要與求助字條
│  ├─ wellbeing_signals.py              v1.3-A 六類身心線索（只記原話，不計分）
│  └─ explain.py                        v1.3-B 虛構對話離線重播
├─ models/database.py     SQLite（個案、同意、對話狀態）
├─ data/                  南投資源、30 組模擬案例、可解釋重播虛構情境
├─ templates/, static/    頁面、CSS、JavaScript
├─ tests/                 unittest 回歸測試（不連網）
├─ scripts/               run_local.ps1、run_tests.ps1
└─ docs/                  交接文件、變更紀錄、archive/ 舊版提示詞快照
```

## 目前功能

- 一般對話以 **1–4 個短句**為原則，每輪最多一個問題；模型溫度 **0.8**。沒有設定 Gemini／OpenAI 金鑰，或模型回覆未通過規則檢查時，使用本機備援回覆（畫面上會標示）。
- 學生確認資料使用說明後才能開始對話；暱稱、學校、信箱皆可留白。系統只檢查信箱格式，**沒有驗證信箱是否屬於學校**，也沒有自動通知。學生端不顯示風險分數；橙色和紅色仍會呈現求助資訊。
- 紅色危機顯示可點選的 `tel:119`、`tel:110`、`tel:1925`；燈號只會提高，後續短回覆不會降低歷史最高風險。
- 自然對話沒有填正式量表時，後台顯示「未施測」；完整填寫六題才有正式 BSRS-5 分數。
- 後台需密碼登入；「已聯絡／已轉介」需真人確認並填寫紀錄。
- `/demo`：30 組模擬案例只讀檢驗，與真實個案資料表分開。
- `/explain`（v1.3-B）：以虛構對話重播完整規則流程，逐輪列出原話證據、六類線索已知／未知、規則來源、歷史最高燈號與對應行動。**不呼叫模型、不寫入資料庫、不建立個案。**
- 情境一致性（v1.3-A.2）：學生分享開心或期待的事時，回覆跟著那份好心情；模型若自行加上「壓力、緊繃、喘息」等學生沒說的狀態，會被規則檢查擋下改用本機回覆。

## Windows PowerShell 逐步啟動

1. 開啟 PowerShell，切換到含有 `app.py` 的目錄（請換成你自己電腦上的實際路徑）：
   ```powershell
   cd "D:\桌面\檔案處理區\蔡睿恩\anla_youth_v1.3-A.1_integrated_source_20261021 (1)\anla-youth-v1.3-A.1"
   ```
2. 第一次使用時建立虛擬環境並安裝依賴（建議 Python 3.10 以上）：
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
3. **在同一個 PowerShell 視窗**設定後台密碼（自行選一組長且不易猜的字串）：
   ```powershell
   $env:WORKBENCH_PASSWORD = Read-Host "設定後台密碼"
   ```
   如果要使用 Gemini，在同一視窗另設金鑰（不要把金鑰貼在聊天或截圖裡）：
   ```powershell
   $env:GEMINI_API_KEY = Read-Host "貼上 Gemini API 金鑰"
   $env:LLM_PROVIDER = "gemini"
   $env:GEMINI_MODEL = "gemini-2.5-flash"
   ```
   模型是否可用、額度和錯誤請以自己的 Google AI Studio 帳號與實際回應為準。OpenAI 介面程式碼存在，但尚未完成實測切換。
4. 啟動（預設埠 5000，可加 `-Port 5002`）：
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\run_local.ps1
   ```
5. 瀏覽器開啟學生頁 <http://127.0.0.1:5000/>；後台 <http://127.0.0.1:5000/login>；登入後可開 `/counselor`、`/demo`、`/explain`。若要分別測試學生和後台的 session，可用不同瀏覽器或私密視窗。
6. 停止伺服器按 `Ctrl+C`。每次開新的 PowerShell，要重新設定只存於當前視窗的環境變數。

## 驗證

在專案目錄執行（測試資料庫寫到暫存檔，結束後刪除）：
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
```
2026-10-22 在本機 Python 3.12 + Flask 3 執行：**165 項，164 通過、1 跳過（誇飾語句待專業覆核）、0 失敗**。測試只驗證程式行為，不等於臨床效度、危機辨識完整率或正式部署驗收。

## 資料與部署

- 本包不含真實資料庫、API 金鑰、`.env` 或使用者對話。執行後會在專案目錄產生 `anla_youth.db`（已列入 `.gitignore`）；其中可能有使用者填寫的信箱及對話片段，請妥善保管，不要上傳公開儲存庫。
- 本機預設僅監聽 `127.0.0.1` 且關閉 debug；不要把 Flask 開發伺服器直接公開到網際網路。
- 若要整合回你 Windows 上正在運作的版本，請先備份，再逐檔比較，尤其是資料庫、提示詞及自訂介面。
