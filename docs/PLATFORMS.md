# 四平台執行與封裝說明（Windows / macOS / iOS / Android）

> 對應《專案開發計畫》貳.二與 Master Prompt Phase 4。本文件只描述封裝與部署；聊天、分級與安全邏輯都在同一份 Flask 伺服器（`app.py`）裡，所有平台看到的是同一套網頁。

## 一、架構一覽

| 平台 | 形式 | 伺服器在哪裡 | 產物 |
|---|---|---|---|
| Windows | `desktop_launcher.py` + pywebview（Edge WebView2 原生視窗） | 預設內建（All-in-One）；可改連遠端 | `dist/AnlaYouth/AnlaYouth.exe`、`AnlaYouth_Setup.exe` |
| macOS | 同一份 `desktop_launcher.py`（Cocoa WebKit 原生視窗） | 同上 | `dist/AnlaYouth.app`、`AnlaYouth.dmg` |
| iOS | ① PWA（Safari 加入主畫面）② Capacitor 外殼 | 一定是遠端（HTTPS） | PWA 免安裝檔；`.ipa` 需 Mac + Apple 簽章 |
| Android | ① PWA（Chrome 安裝）② Capacitor 外殼 | 一定是遠端（HTTPS，或開發用區網 HTTP） | `AnlaYouth-debug.apk` |

桌面版的兩種模式：

- **All-in-One（預設）**：啟動器在背景執行緒以 `127.0.0.1` 啟動 Flask，等 `/health` 回應後開視窗。只綁本機位址，同網路的其他裝置連不到。優先使用固定埠 `51735`（網頁偏好如主題是依「主機＋埠」記憶的），被占用時自動改用空閒埠；可用 `ANLA_DESKTOP_PORT` 改。
- **遠端模式**：`AnlaYouth.exe --server https://你的伺服器` 或設定環境變數 `ANLA_SERVER_URL`，只開視窗，不在本機啟動伺服器。非 HTTPS 的對外網址會顯示警告。

找不到 pywebview 或原生視窗啟動失敗（例如舊版 Windows 缺 WebView2 Runtime）時，會自動改用系統瀏覽器；打包版會跳出對話框，按「確定」即停止本機服務。也可以加 `--browser` 直接用瀏覽器。

## 二、環境變數與資料位置

| 變數 | 用途 |
|---|---|
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | 模型金鑰。**只從環境變數讀取，安裝包內不含任何金鑰。**未設定時依 `config.py` 的 `LLM_PROVIDER` 行為（`auto` 會退回內建回覆）。 |
| `WORKBENCH_PASSWORD` | 輔導工作台密碼，只從環境變數讀取。 |
| `ANLA_SERVER_URL` | 桌面遠端模式；行動版建置時寫入 Capacitor 設定。 |
| `ANLA_DESKTOP_PORT` | All-in-One 模式優先使用的本機埠（預設 51735）。 |
| `DATABASE_PATH` | 自訂 SQLite 位置；未設定時啟動器自動指向下列使用者資料夾。 |

本機資料（SQLite、加密金鑰檔 `<db>.key`、`launcher.log`、WebView 儲存）放在：

- Windows：`%APPDATA%\AnlaYouth\`
- macOS：`~/Library/Application Support/AnlaYouth/`
- Linux：`$XDG_DATA_HOME/AnlaYouth/`（預設 `~/.local/share/AnlaYouth/`）

解除安裝**不會**刪除這個資料夾（避免誤刪紀錄）；要清除請手動刪除。`launcher.log` 只記錄啟動結果與錯誤，不記錄每一筆請求網址。

設定環境變數的方式：

- Windows（永久，對之後啟動的程式生效）：`setx GEMINI_API_KEY "你的金鑰"`，再重新開啟 App。
- macOS：從 Finder 啟動的 App 不會讀 shell 設定檔。可在終端機執行
  `GEMINI_API_KEY=你的金鑰 /Applications/AnlaYouth.app/Contents/MacOS/AnlaYouth`，
  或改用遠端模式連到已設好金鑰的伺服器（建議）。

## 三、Windows

### 從原始碼執行

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-desktop.txt
.venv\Scripts\python desktop_launcher.py                 # All-in-One
.venv\Scripts\python desktop_launcher.py --server https://anla.example.tw   # 遠端
.venv\Scripts\python desktop_launcher.py --check         # 只做 /health 檢查，印出 OK
```

### 打包

```powershell
.venv\Scripts\python build_desktop.py --smoke            # → dist\AnlaYouth\AnlaYouth.exe，並執行打包版 --check
.venv\Scripts\python build_desktop.py --smoke --installer  # 另需 Inno Setup 6.3+，→ dist\AnlaYouth_Setup.exe
```

- `build_desktop.py` 只封裝 `templates/`、`static/`、`data/` 與程式碼；建置前會檢查這三個資料夾，發現 `*.db`、`.env`、`*.key` 等檔案就中止；建置後再檢查產物內沒有資料庫或 `.env`。
- 安裝精靈腳本：`packaging/AnlaYouth.iss`（UTF-8 含 BOM）。也可手動執行 `ISCC /DMyAppVersion=1.3.1 packaging\AnlaYouth.iss`。預設免系統管理員權限，安裝到使用者資料夾。
- Windows 11 內建 WebView2；Windows 10 若缺少，請安裝 Microsoft「Evergreen WebView2 Runtime」，否則會改用瀏覽器開啟。

## 四、macOS

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-desktop.txt
python desktop_launcher.py --check
python build_desktop.py --smoke --dmg                    # → dist/AnlaYouth.app、dist/AnlaYouth.dmg（hdiutil）
python build_desktop.py --dmg --dmg-tool create-dmg      # 若已 brew install create-dmg，可產生較美觀的拖曳安裝視窗
```

- PyInstaller 不能跨平台編譯：`.app` 必須在 Mac 上（或 GitHub Actions 的 macOS 機器）建置。
- `macos-latest` 是 Apple Silicon（arm64），產出的 App 不能在 Intel Mac 上執行；需要 Intel 版時請在 Intel Mac 上自行建置。

## 五、iOS / Android：PWA（實戰首選，免安裝檔）

前提：伺服器已用 **HTTPS** 部署（Service Worker、離線頁與「加入主畫面」的完整體驗都要求 HTTPS；只有 `localhost` 例外）。區網 `http://192.168.x.x` 仍可開網頁，但離線快取不會生效。

**iPhone / iPad（Safari）**
1. 用 Safari 開啟伺服器網址（或掃描網頁上的 QR Code）。必須是 Safari，其他瀏覽器在部分 iOS 版本沒有「加入主畫面」。
2. 點下方「分享」按鈕 → 「加入主畫面」→ 「新增」。
3. 從主畫面圖示開啟，即為無網址列的獨立視窗。

**Android（Chrome）**
1. 用 Chrome 開啟伺服器網址。
2. 點右上「⋮」→「安裝應用程式」（或「加到主畫面」）→「安裝」。
3. 從桌面或應用程式清單開啟。

## 六、Android / iOS：Capacitor 外殼

`mobile/` 是一個只含設定的 Capacitor 6 專案（`appId: tw.nantou.anlayouth`，`appName: 安啦會客室`）。App 本身不含聊天邏輯，只把 WebView 指向 `server.url`；連不上時顯示 `mobile/www/index.html`（說明頁＋1925／1995／1980／110 撥號按鈕）。

伺服器網址在**建置時**寫入：

```bash
cd mobile
npm install
ANLA_SERVER_URL=https://anla.example.tw node scripts/configure-server.mjs   # Windows PowerShell：$env:ANLA_SERVER_URL="..."; node scripts/configure-server.mjs
```

- `https://` → 正式用，`cleartext: false`。
- `http://` 只接受區網／本機位址（10.x、172.16–31.x、192.168.x、127.x、localhost、*.local），並自動開啟 Android `cleartext`，只適合開發與現場展示。其他 `http://` 網址會被拒絕。
- 未設定時移除 `server.url`，App 只會顯示「尚未設定伺服器」說明頁。加 `--require` 可讓未設定視為錯誤。
- 這支腳本會改寫 `capacitor.config.json` 與 `www/server-config.js`；本機測完若不想提交私人網址，請 `git checkout mobile/capacitor.config.json mobile/www/server-config.js`。

### Android（debug APK）

需要 Node 18+、JDK 17、Android SDK（Android Studio 內建）。

```bash
cd mobile
npx cap add android        # 第一次；產生 mobile/android/（已加入 .gitignore）
npx cap sync android
cd android && ./gradlew assembleDebug    # Windows：gradlew.bat assembleDebug
# 產物：mobile/android/app/build/outputs/apk/debug/app-debug.apk
```

選 Capacitor 6.2.1 是因為它使用 JDK 17；Capacitor 7 以上需要 JDK 21。Capacitor 6 的 targetSdk 為 34，側載安裝沒問題，但**上架 Google Play 需要較新的 targetSdk**，屆時請升級 Capacitor 與 JDK。

### iOS（.ipa）

- 一定要 **Mac + Xcode**。`npx cap add ios` → `npx cap open ios`，在 Xcode 選擇 Team 後建置。
- 安裝到實機：免費 Apple ID 的個人簽章只能裝到自己的裝置且約 7 天過期；要給其他人安裝（TestFlight / App Store / Ad Hoc）需要付費的 Apple Developer Program 帳號與憑證、描述檔。
- 若要連區網 HTTP 伺服器，需在 `ios/App/App/Info.plist` 加入 ATS 例外（`NSAppTransportSecurity` → `NSAllowsLocalNetworking = YES`）；正式版請用 HTTPS。
- 對多數使用情境，iOS 用 PWA 即可，不需要 `.ipa`。

## 七、GitHub Actions 自動建置

工作流程：`.github/workflows/build_cross_platform.yml`。觸發條件：push 到 `main`、push `v*` 標籤、或在 Actions 頁面手動執行（workflow_dispatch）。

| Job | 機器 | 內容 | 下載的 Artifact |
|---|---|---|---|
| smoke | ubuntu-latest | 只裝 `requirements.txt`，執行 `python desktop_launcher.py --check` | — |
| windows | windows-latest | 原始碼 `--check` → PyInstaller → 打包版 `--check` → 以 choco 安裝 Inno Setup（若尚未安裝）→ ISCC | `AnlaYouth-windows`（`AnlaYouth_Setup.exe`、免安裝 zip） |
| macos | macos-latest | 原始碼 `--check` → PyInstaller `.app` → 打包版 `--check` → hdiutil `.dmg` | `AnlaYouth-macos`（`AnlaYouth.dmg`） |
| android | ubuntu-latest | Node 20、JDK 17 → `configure-server.mjs` → `cap add android` → `./gradlew assembleDebug` | `AnlaYouth-android-debug`（`AnlaYouth-debug.apk`） |
| ios（選用） | macos-latest | 手動觸發時勾選 `build_ios`；`cap add ios` + `xcodebuild` 模擬器版、不簽章，只做編譯檢查，失敗不影響其他 Job | — |

- 行動版要連的伺服器：在 GitHub 專案 Settings → Secrets and variables → Actions → **Variables** 新增 `ANLA_SERVER_URL`（這是公開網址，不是祕密）。未設定時 APK 只會顯示說明頁。
- 下載：Actions → 選擇該次執行 → 頁面底部 Artifacts。GitHub 預設保留 90 天。
- 工作流程不需要、也不使用任何 API 金鑰。

## 八、簽章與信任提示（重要）

- **Windows**：CI 產出的 `.exe` 未經程式碼簽章，第一次執行會出現 SmartScreen「Windows 已保護您的電腦」→「其他資訊」→「仍要執行」。正式發佈需購買程式碼簽章憑證（OV/EV）並以 `signtool` 簽署 `AnlaYouth.exe` 與 `AnlaYouth_Setup.exe`。
- **macOS**：`.app` 只有 PyInstaller 的 ad-hoc 簽章、未經 Apple 公證（notarization）。下載後 Gatekeeper 會阻擋：對 App 按右鍵 →「打開」，或到「系統設定 → 隱私權與安全性」允許；也可 `xattr -dr com.apple.quarantine /Applications/AnlaYouth.app`。正式發佈需 Developer ID 憑證 + `notarytool`。
- **Android**：CI 只產生以 debug 金鑰簽署的 APK，可側載（需允許「安裝不明來源的應用程式」），不能上架。Release APK/AAB 需自備 keystore（存在 GitHub Secrets），並以 `assembleRelease`/`bundleRelease` + 簽章設定建置；本專案尚未設定。
- **iOS**：見第六節，需要 Apple 簽章；CI 不產生 `.ipa`。

## 九、驗證狀態（誠實揭露）

以下為 2026-10-22 在開發者的 Windows 11 電腦（Python 3.12.10、pywebview 6.2.1、PyInstaller 6.22.3）上的實測結果。

| 項目 | 狀態 | 說明 |
|---|---|---|
| `py_compile desktop_launcher.py build_desktop.py` | ✅ 已驗證 | |
| 原始碼 `desktop_launcher.py --check`（All-in-One） | ✅ 已驗證 | 印出 `OK mode=all-in-one …`，exit 0 |
| 遠端模式 `--check --server` / `ANLA_SERVER_URL` | ✅ 已驗證 | 對本機伺服器 exit 0；連不到的網址 exit 1 |
| `build_desktop.py --smoke`（Windows 打包） | ✅ 已驗證 | 產生 `dist\AnlaYouth\AnlaYouth.exe`，打包版 `--check` exit 0 |
| 打包版預設資料庫位置 | ✅ 已驗證 | 未設 `DATABASE_PATH` 時寫到 `%APPDATA%\AnlaYouth\anla_youth.db` |
| 打包版 GUI（WebView2 視窗） | ✅ 已驗證 | 視窗標題正確、WebView2 子程序啟動、`/`、`/resources`、`/static/*` 回 200；關閉視窗後程序結束 |
| Inno Setup `AnlaYouth_Setup.exe` | ⚠️ 未驗證 | 本機未安裝 Inno Setup；腳本語法未經 ISCC 編譯 |
| macOS `.app` / `.dmg` | ⚠️ 未驗證 | 需 Mac 或 GitHub Actions macOS 機器 |
| Capacitor `npm install`、`cap add android` | ✅ 已驗證 | 於暫存複本執行；設定正確複製到 Android 專案 |
| `configure-server.mjs` 網址規則 | ✅ 已驗證 | HTTPS 通過、區網 HTTP 開 cleartext、外網 HTTP 與非 http(s) 拒絕 |
| Android `./gradlew assembleDebug` | ⚠️ 未驗證 | 本機無 Android SDK；交由 CI |
| iOS `cap add ios` / `xcodebuild` | ⚠️ 未驗證 | 需 Mac；CI 中為選用、實驗性 Job |
| 工作流程 YAML | ✅ 語法已解析 | 以 PyYAML 解析通過；尚未在 GitHub 上實際執行 |
| PWA 安裝流程（iOS / Android） | ⚠️ 未驗證 | 依賴其他人實作的 `static/manifest.json`、`static/sw.js` 與 HTTPS 部署 |
