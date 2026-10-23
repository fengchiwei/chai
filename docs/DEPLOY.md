# 部署：Render 網站與 GitHub Releases 下載

GitHub Pages 只能放靜態網頁，跑不了這個專案的 Python 後端（AI 對話、資料庫、工作臺）。所以分成兩條路：

- **線上網站**：程式碼在 GitHub，由 Render 代管執行，每次推送到 main 會自動更新。
- **下載安裝版**：推送 `v*` 標籤時，GitHub Actions 自動建置安裝檔並附到 GitHub Releases 頁面。

## 一、Render 網站（第一次設定約 5 分鐘）

1. 用 GitHub 帳號登入 <https://render.com>。
2. 右上角 **New → Blueprint**，選 `timmango123/chai` 這個 repository。Render 會讀取根目錄的 `render.yaml`。
3. 畫面會要求填兩個值（只存在 Render，不會進 GitHub）：
   - `WORKBENCH_PASSWORD`：輔導工作臺的登入密碼，請用夠長、不好猜的密碼。
   - `LLM_API_KEY`：AI 服務的金鑰（Gemini、Claude、OpenAI 相容服務皆可，會依開頭自動判斷）。
4. （選用）想要自然的雲端朗讀聲音，在 Render 服務的 **Environment** 加上 `AZURE_SPEECH_KEY` 與 `AZURE_SPEECH_REGION`（Azure 入口網站建立「語音服務」資源即可取得，有免費額度）。主要金鑰是 Gemini 或 OpenAI 時，不用另外設定就有該家的語音可選。
5. 按 **Apply**。建置完成後，網址會是 `https://anla-youth-xxxx.onrender.com` 這類格式，學生頁在 `/`，工作臺在 `/login`。
6. 第一次登入工作臺時帳號留白（內建管理員 `admin`），密碼是 `WORKBENCH_PASSWORD`；登入後到「👥 工作臺帳號」為每位老師建立個人帳號。**免費方案重新部署會清空資料庫，個人帳號也會一起不見**，內建管理員不受影響。

`render.yaml` 已經設定好：

| 設定 | 值 | 說明 |
|---|---|---|
| 啟動 | `gunicorn app:app --workers 1 --threads 8` | 單一行程：對話鎖、速率限制、模型健康狀態都在記憶體裡 |
| `SECRET_KEY`、`ANLA_DB_KEY` | Render 自動產生 | 登入 session 與資料庫欄位加密金鑰 |
| `COOKIE_SECURE` | `true` | Render 一律走 HTTPS |
| `TRUSTED_PROXY_HOPS` | `1` | 登入鎖定依真實來源 IP 計算 |
| 健康檢查 | `/health` | |
| 手機掃碼網址 | 自動使用 Render 提供的 `RENDER_EXTERNAL_URL` | |

**免費方案的限制（請知悉）：**
- 15 分鐘沒人使用會休眠，下一個人開啟要等約 30–60 秒。
- 沒有永久磁碟：每次重新部署或重新啟動，SQLite 資料庫（對話暫存、個案、稽核紀錄）都會清空。展示與試用沒問題；正式給學生使用前，請改用付費方案並在 Render 加掛 Persistent Disk，再把 `DATABASE_PATH` 設到磁碟路徑（例如 `/var/data/anla_youth.db`）。
- 主機在新加坡。正式使用前，請學校確認資料存放在境外主機是否符合規定。

## 二、GitHub Releases 下載安裝版

推送一個 `v` 開頭的標籤，例如：

```bash
git tag v2.5.12
git push origin v2.5.12
```

`.github/workflows/build_cross_platform.yml` 會依序建置，全部成功後在 Releases 頁面建立同名版本，附上：

| 檔案 | 平台 |
|---|---|
| `AnlaYouth_Setup.exe` | Windows 安裝程式 |
| `AnlaYouth-windows-portable.zip` | Windows 免安裝版 |
| `AnlaYouth.dmg` | macOS |
| `AnlaYouth-debug.apk` | Android（debug 版） |

注意：
- 安裝檔都**沒有程式碼簽章**。Windows 會跳出 SmartScreen 警告（按「其他資訊 → 仍要執行」），macOS 要按右鍵「打開」。
- 桌面版在使用者自己的電腦上跑伺服器，AI 金鑰要在那台電腦上設定。
- Android App 只是外殼，會開啟 repository 變數 `ANLA_SERVER_URL` 指定的網址。Render 網址確定後，到 GitHub repository 的 **Settings → Secrets and variables → Actions → Variables** 新增 `ANLA_SERVER_URL`，再推下一個標籤，APK 才會連到線上網站。
