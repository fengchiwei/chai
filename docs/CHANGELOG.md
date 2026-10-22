# 變更紀錄

> 依 `PROJECT_STATUS_20261021.md` 與 `專案開發計畫.md`（v2.3）續作。所有測試只使用虛構句子，不連網。

## 2026-10-22：v2.3（專案開發計畫五個 Phase）

結果：單元測試 225 項全部通過（0 跳過）；P01–P10 閘門 10.00 / 10、高危漏報 0；突變測試 6/6。完整說明見 `EVALUATION_REPORT_95.md`。

### v1.3-B.1 服務韌性與提示詞注入（先於 v2.3 完成）
- `engine/dialogue_ai.py`：分析＋回覆共用每輪時間預算（`LLM_TURN_BUDGET`，預設 30 秒）；逾時、非 JSON、429、401/403、供應商封鎖分別分類；429 依 `Retry-After`（上限 300 秒）、金鑰錯誤 300 秒、連續 3 次連線失敗 30 秒暫停雲端呼叫，安全回覆不受影響；回應附 `fallback_reason`。
- `engine/prompt_guard.py`：學生文字送模型前中和偽造的 `【…】` 段落、`system:` 角色前綴與特殊 token；儲存的原話不變。模型回覆外洩內部欄位、提示詞原文或宣稱「已解除限制」時改用本機回覆；被要求顯示提示詞時說明不能提供。
- 系統提示詞新增【資料與指令界線】。

### Phase 1：跨領域風險分流
- `engine/rules.py`：LIN-01 誇飾遮蔽（熱／累／餓…到想死）、「想自殺／有自殺念頭」、「吞了很多顆」；第三人稱旁白（閨蜜傳 LINE 跟我說…）不再被當成本人。
- `engine/triage.py`：誇飾語 → 黃色＋`pending_disambiguation`；所有結果附 `theoretical_basis`。
- `engine/dialogue_policy.py`：PSY-02 累贅感／歸屬受挫、PSY-03 困頓感跨輪累積（兩者並存或困頓＋其一 → 橙）；SOC-05 第三人稱擴充與 `secondary_trauma_risk`；SIG-02 先驗 ≥2 項時誇飾升橙；DYN-04 連續負面、突兀道別、深夜（只由聊天路由提供時間，測試不受時鐘影響）；「只是抱怨／開玩笑」視為澄清；否定加上「不覺得、不認為」。
- `engine/wellbeing_signals.py`：家人／朋友只有伴隨衝突字詞才記「人際與壓力」；補「翻到凌晨三點才睡著」「上課恍神聽不懂」；安全證據取第一個逐字片段。
- 回覆：誇飾語用自然的一次確認；第三人稱危機加上「打破保密迷思」與安撫；澄清後回到輕鬆對話。
- 解除 `test_hyperbole_review_only` 的跳過（行為改為黃色＋軟性確認，仍需專業覆核）。

### Phase 2：資安
- `engine/privacy_scrubber.py`：送模型前遮罩姓名、地址、電話、身分證／學號、Email／社群帳號（提示詞記憶與歷史一併處理）。
- `engine/crypto_store.py`＋`models/database.py`＋`engine/referral.py`：`student_contexts` 與 `cases` 敏感欄位 AES-256-GCM（缺 `cryptography` 時標準庫加密＋HMAC 備援）；舊明文資料可讀；`PRAGMA secure_delete`。
- 稽核日誌 SHA-256 雜湊鏈與 `verify_audit_chain()`；工作臺查閱個案寫入稽核。
- 新增相依：`cryptography`、`segno`。

### Phase 3：風格、前端與儀表板
- 四種回覆風格（`reply_style`）與安全優先覆寫；學生自己說「不要問我／不要建議」時也遵守；拒絕「冷血酸民」等有害角色；理性風格三段結構；綠燈對話擋下「喘息空間、緊繃感…」等諮商詞。
- 前端：四套主題、風格膠囊、Boss Key 單字卡偽裝、離線求助卡與 4-7-8 呼吸球、PWA（`/manifest.json`、`/sw.js`、`/offline`）、手機掃碼（`/api/qr.svg`、`/api/install-info`）。
- 可解釋：`/explain` 原話螢光筆、理論代號、確認危機（實線）與待消歧（虛線）；`/counselor` 摘要加上判讀依據與六類線索（只在學生同意分享的快照中）；`/demo` 顯示理論代號。

### Phase 4：四平台
- `desktop_launcher.py`、`build_desktop.py`、`packaging/AnlaYouth.iss`、`mobile/`（Capacitor 6）、`.github/workflows/build_cross_platform.yml`、`docs/PLATFORMS.md`。Windows `.exe` 已本機建置並開窗；其他平台只寫好 CI，尚未實跑。

### Phase 5：9.5 閘門
- `tests/eval_95_gate.py`（P01–P10、五維度評分、含完整單元測試）、`tests/eval_mutation_check.py`、`EVALUATION_REPORT_95.md`。
- 突變測試發現評測漏洞（P06 本身的「不要問我」掩蓋樹洞按鈕是否生效），已加入只按按鈕的探針。

### 文獻回顧指出、已在程式註解中修正的落差
- PSY-04：DSM-5 的 NSSI 提案標準是「過去一年 ≥5 天」，**不是**計畫書寫的「兩週」。
- DYN-04：幾輪對話無法測量臨界慢化，只當作提醒真人的啟發式。
- SIG-02：沒有計算機率；「≥2 項」沒有預測效度證據。

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
