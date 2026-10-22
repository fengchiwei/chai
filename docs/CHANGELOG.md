# 變更紀錄

> 依 `PROJECT_STATUS_20261021.md` 第 5、6 節的開發計畫續作。所有測試只使用虛構句子，不連網。

## 2026-10-22：v1.3-A.2 情境一致性 ＋ v1.3-B 可解釋儀表板

### 測試套件修復（完整套件從 15 失敗、2 錯誤 → 0 失敗）

- 上次紀錄的「8 匯入錯誤」是環境未安裝 Flask；安裝後實際為 **149 項：15 失敗、2 錯誤**。
- **Gemini 請求無法被測試替身攔截**：`dialogue_ai.py` 為了 Windows proxy 問題改用 `requests.Session().post`，但所有測試都替換 `requests.post`。改回 `requests.post(..., proxies=DIRECT_CONNECTION)`：以 `None` 覆蓋環境／登錄檔 proxy，效果等同原本的 `trust_env=False` 直連，且可被測試攔截（已驗證設定 `HTTPS_PROXY` 時不會走 proxy）。修好 8 項。
- **本機備援回覆丟失學生原話**：v1.2.1 改成通用模板後，「今天真的很開心」會被回成「這件事讓你不好受」。改為只重用學生自己的關鍵詞（主題、感受、轉折），不整句照抄。修好其餘 9 項。

### v1.3-A.2 情境一致性（計畫第 3 項）

- `engine/dialogue_reply.py`
  - 開心／期待且沒有困擾字詞時，本機回覆跟著好心情，問題改為「想多說說這件事嗎？」，不再追問想法或渴望；前文是好消息、本輪是中性補充（例如「上次我還贏了他一局」）也一樣。
  - 「沒有很開心」不會被反映成「很開心」。
  - 新規則檢查 `invented_distress`：學生只分享好消息時，模型回覆若出現學生沒說的「壓力、緊繃、喘息、不好受……」，退回本機回覆。學生自己提到的字詞不受影響。
- `engine/dialogue_ai.py`：系統提示詞加一句「分享開心、期待的事時就跟著那份好心情回應」。
- 不改變任何分流規則或安全決策。

### v1.3-A 線索模組修正（`engine/wellbeing_signals.py`，版本字串不變以相容既有對話狀態）

- 紅／橙安全證據在後續輪次被沿用時，保留**原始輪次**，不再改標為最新輪（原本會讓證據對不回原話）。
- 「我沒有說謊，朋友說他想死」不再被記成「提到可求助對象」（`沒有` 內的 `有` 誤配），第三人稱「朋友說／同學說」的句子不寫入本人身心線索。安全欄位仍由既有安全狀態標為需真人覆核。

### v1.3-B 可解釋儀表板（計畫第 4 項的第一步）

- `engine/explain.py`、`data/explain_scenarios.json`（9 組虛構情境）、`templates/explain.html`、`static/js/explain.js`。
- 路由：`/explain`、`/api/explain/scenarios`、`/api/explain/<id>`，皆需工作臺登入、`Cache-Control: no-store`。
- 以與 `/api/chat` 相同的順序離線重播（分流 → 對話決策 → 線索 → 本機回覆），**不呼叫模型、不寫入資料庫、不建立個案**；只接受標記 `"fictional": true` 的情境。
- 每輪顯示：規則命中字詞與層級、對話安全核對（訊號、類型、對象、依據原話）、判讀理由、對話任務、歷史最高燈號；六類線索顯示已知／未知與原話是否逐字核對。
- 情境 EX-03「我今天跟我媽吵架」依既有黃色規則字詞「吵架」為黃色；儀表板列出來源供專業覆核，未修改規則。

### 新增測試

- `tests/test_context_consistency_v13a2.py`（7 項）、`tests/test_explain_v13b.py`（9 項）。
- 完整套件：**165 項，164 通過、1 跳過、0 失敗**（`scripts/run_tests.ps1`）。

### 資料夾整理

- 交接文件移到 `docs/`；未被程式讀取、且已與 `dialogue_ai.py` 不同步的 `system_prompt.txt` 移到 `docs/archive/system_prompt_v1.3-A.1.txt`（實際使用的提示詞以 `engine/dialogue_ai.py` 為準）。
- 新增 `.gitignore`（`.venv`、`*.db`、`.env` 等）、`scripts/run_tests.ps1`、`scripts/run_local.ps1`。
- README 更新：專案結構、正確的溫度與回覆長度、移除不存在的 `run.bat`／`test_cases.py`。

### 仍未完成（不得誤稱已完成）

- 雲端模型（Gemini／OpenAI）的實際輸出比較；情境一致性只以規則與替身測試驗證，未用真實 API 驗收。
- 誇飾語句（「熱到想死」）仍待專業覆核，相關測試保留跳過。
- 服務韌性壓力測試、提示詞注入、跨使用者隔離與 CSRF／授權稽核、行動裝置實機測試。
- v1.3-B 目前只重播虛構情境；尚未在工作臺個案頁顯示真實個案的證據摘要（需另行授權與資料保護設計）。
