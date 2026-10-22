"""少年仔、安啦會客室：桌面啟動器（Windows / macOS）。

兩種模式：
  * All-in-One（預設）：在背景執行緒以 127.0.0.1 啟動 app.py 的 Flask `app`
    （優先用固定埠 51735 以保留網頁偏好；被占用時改用空閒埠；--check 一律用空閒埠），
    等 /health 回應後開啟原生視窗（Windows: Edge WebView2；macOS: Cocoa WebKit）。
  * 遠端模式：`--server URL` 或環境變數 ANLA_SERVER_URL，只開視窗連到該伺服器。

其他：
  --check     啟動（或連線）伺服器、呼叫 /health，印出 OK 後以 0 結束；不開任何視窗（CI 煙霧測試用）。
  --browser   不用原生視窗，改開系統瀏覽器（pywebview 不可用時也會自動退回此模式）。

資料與祕密：
  * SQLite 放在使用者資料夾（Windows: %APPDATA%\\AnlaYouth；macOS: ~/Library/Application Support/AnlaYouth；
    Linux: $XDG_DATA_HOME/AnlaYouth），透過環境變數 DATABASE_PATH 在匯入 app 之前設定；
    若使用者已自行設定 DATABASE_PATH 則尊重之。
  * GEMINI_API_KEY / WORKBENCH_PASSWORD 等只從環境變數讀取；本程式不寫入、不封裝任何金鑰。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

APP_ID = "AnlaYouth"
WINDOW_TITLE = "少年仔、安啦會客室"
HEALTH_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# 路徑
# ---------------------------------------------------------------------------

def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> str:
    """templates/、static/、data/ 與 app.py 所在的根目錄。

    PyInstaller 打包後是 sys._MEIPASS（one-folder 時為 dist/AnlaYouth/_internal）；
    原始碼執行時是本檔所在資料夾。app.py 用 os.path.dirname(__file__) 找 data/，
    Flask 用模組位置找 templates/、static/，兩者在凍結後都會落在 _MEIPASS，
    所以只要 build_desktop.py 把三個資料夾放在 _MEIPASS 根目錄即可，不需修改 app.py。
    """
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.abspath(__file__))


def user_data_dir() -> str:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    path = os.path.join(base, APP_ID)
    os.makedirs(path, exist_ok=True)
    return path


def ensure_std_streams() -> None:
    """PyInstaller 無主控台（windowed）版本的 sys.stdout/stderr 是 None；改寫到記錄檔，
    讓 --check 的結果與錯誤訊息仍可查看，也避免 logging 寫入 None 時出錯。"""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_path = os.path.join(user_data_dir(), "launcher.log")
    stream = open(log_path, "a", encoding="utf-8", buffering=1)
    stream.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(sys.argv[1:])}\n")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


# ---------------------------------------------------------------------------
# 伺服器
# ---------------------------------------------------------------------------

DEFAULT_DESKTOP_PORT = 51735


def _port_is_free(host: str, port: int) -> bool:
    """以獨占方式試綁定。werkzeug 會設 SO_REUSEADDR，在 Windows 上可能與其他程式共用同一埠，
    所以先用不帶 reuse 的 socket 探測；被占用就改用隨機空閒埠。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


class LocalServer:
    """在背景執行緒執行 app.py 的 Flask app（僅綁定 127.0.0.1）。

    GUI 模式優先使用固定埠（預設 51735，可用 ANLA_DESKTOP_PORT 覆寫）：網頁的 localStorage
    以「主機＋埠」區分，固定埠才能記住主題等偏好；該埠被占用時改用作業系統挑選的空閒埠。
    """

    def __init__(self, preferred_port: int = 0) -> None:
        self.preferred_port = preferred_port
        self.host = "127.0.0.1"
        self._server = None
        self._thread: threading.Thread | None = None
        self.port = 0

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> "LocalServer":
        root = resource_root()
        # app.py / config.py 需在匯入前取得 DATABASE_PATH；已由使用者設定時不覆寫。
        os.environ.setdefault("DATABASE_PATH", os.path.join(user_data_dir(), "anla_youth.db"))
        if root not in sys.path:
            sys.path.insert(0, root)
        os.chdir(root)  # 任何相對路徑都以資源根目錄為準

        import logging

        # 不把每個請求（可能含個案 ID 的路徑）寫進主控台/記錄檔。
        logging.getLogger("werkzeug").setLevel(logging.WARNING)

        from werkzeug.serving import make_server

        from app import app as flask_app  # noqa: E402  (需在設定環境變數後匯入)

        port = self.preferred_port if self.preferred_port and _port_is_free(self.host, self.preferred_port) else 0
        # port=0 交給作業系統挑選空閒埠。
        self._server = make_server(self.host, port, flask_app, threaded=True)
        self.port = self._server.socket.getsockname()[1]
        self._thread = threading.Thread(target=self._server.serve_forever, name="anla-flask", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None


def fetch_health(base_url: str, timeout: float = 5.0) -> dict:
    url = base_url.rstrip("/") + "/health"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    # 本機伺服器不走系統 proxy（Windows 上的 proxy 設定可能攔截 127.0.0.1）。
    handlers = []
    host = urllib.parse.urlsplit(url).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1"):
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    with opener.open(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        if resp.status != 200:
            raise RuntimeError(f"/health HTTP {resp.status}")
    data = json.loads(body)
    if data.get("status") != "ok":
        raise RuntimeError(f"/health 狀態異常：{body[:200]}")
    return data


def wait_for_health(base_url: str, timeout: float = HEALTH_TIMEOUT) -> dict:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return fetch_health(base_url, timeout=3.0)
        except (urllib.error.URLError, OSError, ValueError, RuntimeError) as exc:
            last_error = exc
            time.sleep(0.25)
    raise TimeoutError(f"{base_url}/health 在 {timeout:.0f} 秒內沒有回應：{last_error}")


def normalize_server_url(raw: str) -> str:
    url = raw.strip()
    if "://" not in url:
        url = "http://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"伺服器網址格式不正確：{raw!r}")
    if parts.scheme == "http" and not _is_local_or_lan(parts.hostname):
        print(f"[警告] {url} 未使用 HTTPS；對外網路上請改用 HTTPS，避免對話內容外洩。", file=sys.stderr)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _is_local_or_lan(host: str) -> bool:
    import ipaddress

    if host in ("localhost",) or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


# ---------------------------------------------------------------------------
# 視窗
# ---------------------------------------------------------------------------

def open_native_window(url: str) -> bool:
    """以 pywebview 開啟原生視窗；阻塞到視窗關閉。pywebview 不可用時回傳 False。"""
    try:
        import webview  # pywebview
    except Exception as exc:  # ImportError 或平台後端缺件
        print(f"[資訊] 無法載入 pywebview（{exc}），改用系統瀏覽器。", file=sys.stderr)
        return False

    storage = os.path.join(user_data_dir(), "webview")
    os.makedirs(storage, exist_ok=True)
    try:
        webview.create_window(
            WINDOW_TITLE,
            url,
            width=1100,
            height=800,
            min_size=(380, 600),
            text_select=True,  # 允許複製求助專線等文字
        )
        # private_mode=False + storage_path：保留主題偏好等 localStorage；資料只在本機使用者資料夾。
        webview.start(private_mode=False, storage_path=storage)
        return True
    except Exception as exc:  # 例如 Windows 缺 WebView2 Runtime
        print(f"[資訊] 原生視窗啟動失敗（{exc}），改用系統瀏覽器。", file=sys.stderr)
        return False


def open_in_browser_and_wait(url: str, server: LocalServer | None) -> None:
    webbrowser.open(url)
    if server is None:
        return  # 遠端模式：開完瀏覽器即可結束
    message = f"已在瀏覽器開啟：{url}\n關閉此對話框即停止本機服務。"
    if sys.platform.startswith("win") and is_frozen():
        # 無主控台的打包版：用原生訊息框讓使用者能結束服務（不額外依賴 tkinter）。
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, WINDOW_TITLE, 0x40)
        return
    print(message.replace("關閉此對話框", "按 Ctrl+C"))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# 進入點
# ---------------------------------------------------------------------------

def _env_port() -> int:
    raw = os.environ.get("ANLA_DESKTOP_PORT", "").strip()
    if raw.isdigit() and 0 <= int(raw) <= 65535:
        return int(raw)
    return DEFAULT_DESKTOP_PORT


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="AnlaYouth", description="少年仔、安啦會客室 桌面啟動器")
    parser.add_argument("--server", metavar="URL", default=os.environ.get("ANLA_SERVER_URL", ""),
                        help="遠端模式：連到既有伺服器（也可用環境變數 ANLA_SERVER_URL）")
    parser.add_argument("--check", action="store_true", help="只做 /health 檢查，成功印出 OK 並以 0 結束")
    parser.add_argument("--browser", action="store_true", help="改用系統瀏覽器，不開原生視窗")
    # macOS 從 Finder 啟動時可能帶入 -psn_0_xxxx 參數；忽略未知參數。
    args, _unknown = parser.parse_known_args(argv)
    return args


def main(argv: list[str] | None = None) -> int:
    ensure_std_streams()
    args = parse_args(argv)
    server: LocalServer | None = None

    try:
        if args.server:
            url = normalize_server_url(args.server)
            mode = "remote"
        else:
            # --check 一律用隨機埠，避免與已開啟的桌面版衝突。
            preferred = 0 if args.check else _env_port()
            server = LocalServer(preferred).start()
            url = server.url
            mode = "all-in-one"

        health = wait_for_health(url, timeout=HEALTH_TIMEOUT if server else 10.0)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        if server:
            server.stop()
        return 1

    if args.check:
        db = os.environ.get("DATABASE_PATH", "") if server else "(remote)"
        print(f"OK mode={mode} url={url} policy={health.get('dialogue_policy', '?')} db={db}")
        if server:
            server.stop()
        return 0

    try:
        if args.browser or not open_native_window(url):
            open_in_browser_and_wait(url, server)
    finally:
        if server:
            server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
