# 少年仔、安啦會客室：AI 陪伴與風險預警原型

目前原始碼版本：**v2.4**。開發依據為重新撰寫的 [docs/專案開發計畫_v3.md](docs/專案開發計畫_v3.md)（取代 Gemini 撰寫的 v2.3 計畫）。版本變更見 [docs/CHANGELOG.md](docs/CHANGELOG.md)，9.5 分閉環審查結果見 [EVALUATION_REPORT_95.md](EVALUATION_REPORT_95.md)，文獻依據見 [docs/THEORETICAL_FOUNDATIONS.md](docs/THEORETICAL_FOUNDATIONS.md)，各平台安裝見 [docs/PLATFORMS.md](docs/PLATFORMS.md)。

提供學生對話（四種回覆風格）、語音輸入／朗讀、南投資源、離線求助卡、模擬案例測試、燈號判讀說明，以及需密碼登入的真人覆核工作臺。

**用途界線**：本原型沒有接入學校、公部門、警消或電郵發送服務。它不會替任何人撥號、寄信或通報。分流規則及模型會犯錯，評測分數只是工程回歸指標，**不是臨床效度，也不代表零漏報**。正式供青少年使用前，需另作專業審查、資料保護、身分認證、監控及部署。

## 快速啟動（雙擊）

在專案資料夾雙擊 **`start.bat`**：

1. 第一次使用會自動建立 `.venv` 並安裝套件（需已安裝 Python 3.10 以上）。
2. 詢問後台密碼（輸入時不顯示；直接按 Enter 跳過則後台停用）。
3. 詢問 AI 服務的 API 金鑰：Gemini、Claude、OpenAI、DeepSeek、Groq、OpenRouter、xAI、Mistral 或任何 OpenAI 相容服務都可以，依金鑰開頭自動判斷；判斷不出時會讓你選擇。直接按 Enter 則不接 AI：學生傳訊時只會看到「尚未接上 AI」的說明與求助電話（危險訊息仍有固定安全文字）。
4. 伺服器啟動後自動開啟瀏覽器 <http://127.0.0.1:5000/>。關閉視窗或按 `Ctrl+C` 即停止。

密碼與金鑰只存在該視窗的記憶體，不寫入任何檔案。改埠號可執行 `start.bat -Port 5002`；桌面版視窗請見 `docs/PLATFORMS.md`（`desktop_launcher.py`）。

## 專案結構

```
anla-youth-v1.3-A.1/
├─ start.bat                    雙擊一鍵啟動
├─ app.py, config.py            Flask 路由與環境變數設定
├─ desktop_launcher.py          桌面原生視窗（pywebview）與系統列圖示；build_desktop.py 打包 .exe／.app
├─ engine/
│  ├─ rules.py, triage.py, bsrs5.py      四級分流、誇飾遮蔽（LIN-01）、theoretical_basis
│  ├─ dialogue_policy.py                 對話決策、IPTS／IMV、第三人稱、數位表型、回覆風格
│  ├─ dialogue_ai.py                     模型呼叫、逾時預算、失敗冷卻、風格提示詞
│  ├─ dialogue_reply.py                  安全文字（給 AI 改寫的參考與保險）、送出前規則檢查
│  ├─ prompt_guard.py                    提示詞注入防護與內部設定外洩檢查
│  ├─ privacy_scrubber.py                送模型前個資遮罩
│  ├─ crypto_store.py                    SQLite 欄位加密（AES-256-GCM）
│  ├─ wellbeing_signals.py               六類身心線索（只記原話，不計分）
│  ├─ explain.py                         燈號判讀說明（虛構情境、不寫資料庫）
│  └─ dialogue_role.py, support.py, referral.py, ai_agent.py
├─ models/database.py           SQLite、雜湊鏈稽核日誌
├─ data/                        南投資源、30 組模擬案例、虛構重播情境與 P01–P10
├─ templates/, static/          頁面、四主題 CSS、PWA（manifest、sw.js、離線頁）
├─ tests/                       unittest 回歸測試、eval_95_gate.py、eval_mutation_check.py
├─ mobile/, packaging/, .github/workflows/   Capacitor、Inno Setup、跨平台 CI
├─ scripts/                     start.ps1、run_local.ps1、run_tests.ps1
└─ docs/                        交接、變更紀錄、文獻、平台說明、archive/
```

## 主要功能

- **對話**：一般回覆 1–4 短句、每輪最多一問。學生可選 🍵 溫馨陪伴、⚡ 活潑元氣、🧭 沉穩理性（重點／卡點／下一步）、🤫 純粹樹洞（零問號、零建議）。**任何安全確認都會暫停所選風格**（`style_overridden_by_safety`）。
- **風險分流**：綠黃橙紅四級，燈號只升不降。依文獻擴充：累贅感＋歸屬受挫／困頓感跨輪累積（PSY-02/03）、誇飾語軟性確認（LIN-01）、第三人稱危機與保密迷思（SOC-05）、深夜與突兀道別等啟發式（DYN-04）。每個判斷都有 `theoretical_basis` 代號。
- **自動選模型與故障切換**：依金鑰讀取它能用的對話模型（只讀清單、不耗 token），預設用排名最高的；某個模型額度用完（429）、已停用（404）、過載（503）或逾時，同一則訊息內自動改用下一個（最多 3 個、不超過 30 秒預算），出問題的模型暫停一段時間後再試。學生不用選模型、也看不到模型名稱；排名、使用中的模型與各模型狀態只在工作臺「🤖 AI 模型」面板。
- **回覆一律由 AI 寫**：一般聊天、隱私與身分問題、界線都由 AI 回覆（規則決定的事實當參考內容）。偵測到危險時，AI 依審過的安全文字改寫，必須保留求助電話、不能承諾保密或先問手段，沒通過或超過 12 秒就改用那段固定文字。AI 回覆不了時（沒金鑰、額度用完、全部模型故障、逾時），學生看到誠實的說明與 119／1925，不再有制式的本機對話回覆；回應附 `fallback_reason`。
- **資安**：送模型前遮罩姓名／地址／電話／身分證／帳號；學生訊息與摘錄標成資料、不能偽造提示詞段落；模型回覆若外洩內部設定或宣稱「解除限制」即被擋下。SQLite 對話與個案敏感欄位加密，稽核日誌以 SHA-256 雜湊鏈串接，查閱個案也會留紀錄。
- **學生頁**：對話框上方的 **AI 連線狀態燈**（🟢 AI 連線正常／⚪ 尚未接上 AI／🟠 AI 暫時無法使用＋原因，例如金鑰無效、額度用完、逾時；點一下重新檢查）、四套主題、離線求助卡與 4-7-8 呼吸球、PWA 加入主畫面、手機掃碼安裝。（原計畫的英文單字卡偽裝畫面已依專案負責人決定移除。）
- **工作臺**：`/counselor` 個案摘要含完整對話紀錄（到學生同意分享為止）、原話螢光筆、規則來源、理論代號、六類線索、依類型的通報檢核與處理紀錄時間軸，可列印成乾淨的 A4 版本（留稽核紀錄）；頁尾「🤖 AI 模型」面板可看可用模型、手動選擇或重新偵測；`/explain` 重播虛構情境與 P01–P10；`/demo` 30 組模擬案例。

## 環境變數

| 變數 | 用途 |
|---|---|
| `WORKBENCH_PASSWORD` | 後台密碼；未設定時後台、`/demo`、`/explain` 停用 |
| `LLM_API_KEY` | 雲端模型的金鑰（任一家）。未設定時學生只會看到「尚未接上 AI」的說明。舊的 `GEMINI_API_KEY`、`OPENAI_API_KEY`、`ANTHROPIC_API_KEY` 仍可使用 |
| `LLM_PROVIDER` | `auto`（預設，依金鑰開頭判斷）、`gemini`、`anthropic`、`openai`、`deepseek`、`groq`、`openrouter`、`xai`、`mistral`、`custom` 或 `builtin`。`sk-` 開頭的金鑰可能是 OpenAI 或 DeepSeek，請指定 |
| `LLM_BASE_URL` | `custom` 用的服務網址（任何 OpenAI 相容服務，例如學校自架或 Ollama 的 `http://127.0.0.1:11434/v1`） |
| `LLM_MODEL` | **通常不用設**。系統會依金鑰讀取可用模型並自動選最佳者；也可以在工作臺「AI 模型」面板用下拉選單手動選擇（重啟後保留）。指定的模型排第一順位，故障時仍會切換 |
| `MODEL_AUTO_SELECT` | 預設 `true`；設 `false` 則不讀模型清單，只用 `LLM_MODEL`（或該服務的預設模型） |
| `GEMINI_THINKING` | 預設 `low`：把模型的「思考」降到最低以縮短等待；`default` 則使用模型原本的設定 |
| `LLM_EFFORT` | Claude 等會先思考的模型用的思考程度，預設 `low`（短回覆、等待短）；可設 `medium`、`high`、`xhigh`、`max`，或 `default` 使用模型本身的預設 |
| `ANLA_DB_KEY` | 資料庫加密金鑰（任意長字串）。未設定時自動在資料庫旁產生 `anla_youth.db.key`，**遺失就無法解密**，切勿上傳 |
| `HOST`、`PUBLIC_URL` | 讓手機連入：`HOST=0.0.0.0`；掃碼網址用 `PUBLIC_URL`（手機離線快取需 HTTPS） |
| `LLM_TURN_BUDGET`、`LLM_CONNECT_TIMEOUT` | 每輪模型呼叫合計秒數上限（預設 30）、連線逾時（預設 3） |
| `LLM_CALL_MODE` | `single`（預設，一次結構化呼叫取得線索與回覆）或 `two_stage`（先分析再回覆） |
| `CHAT_RATE_LIMIT`、`LOGIN_MAX_FAILURES`、`CORS_ORIGINS` | 每段對話每分鐘訊息上限（30，橙紅訊息不受限）、後台 10 分鐘內登入失敗上限（5）、允許跨來源的網址（預設不開放） |
| `LLM_CALLS_PER_MINUTE` | 全站每分鐘雲端模型請求上限（120）；超過時學生看到「AI 目前太忙」的說明（危險訊息仍有固定安全文字），控制費用 |
| `TRUSTED_PROXY_HOPS` | 部署在 HTTPS 通道或反向代理後面時的代理層數，登入鎖定才會依真實 IP 計算 |

## Windows PowerShell 逐步啟動

1. 切換到含有 `app.py` 的目錄（換成你自己電腦上的實際路徑）：
   ```powershell
   cd "D:\桌面\檔案處理區\蔡睿恩\anla_youth_v1.3-A.1_integrated_source_20261021 (1)\anla-youth-v1.3-A.1"
   ```
2. 第一次使用：
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
3. 在同一個視窗設定後台密碼（與選用的 AI 服務金鑰 `$env:LLM_API_KEY`；不要貼在聊天或截圖裡）：
   ```powershell
   $env:WORKBENCH_PASSWORD = Read-Host "設定後台密碼"
   ```
4. 啟動：
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\run_local.ps1
   ```

## 驗證

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
.\.venv\Scripts\python.exe tests\eval_95_gate.py
.\.venv\Scripts\python.exe tests\eval_mutation_check.py
```

2026-10-23 本機結果：單元測試 **372 項全部通過**；P01–P10 閘門 **10.00 / 10、高危漏報 0**；突變測試 6/6 防護被偵測。這些只驗證程式行為，雲端模型實際輸出、離線快取與 macOS／Android／iOS 封裝尚未實測（見 `EVALUATION_REPORT_95.md` 第五節）。

## 資料與部署

- 本包不含真實資料庫、API 金鑰、`.env` 或使用者對話。`*.db`、`*.db.key`、`build/`、`dist/` 已列入 `.gitignore`。
- 本機預設只監聽 `127.0.0.1`、關閉 debug；不要把 Flask 開發伺服器直接公開到網際網路。
- 若要整合回 Windows 上正在運作的版本，請先備份，再逐檔比較。舊資料庫的明文資料仍可讀，之後新寫入的會自動加密。
