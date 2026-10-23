"""少年仔、安啦會客室：桌面啟動器（Windows / macOS）。

兩種模式：
  * All-in-One（預設）：在背景執行緒以 127.0.0.1 啟動 app.py 的 Flask `app`
    （優先用固定埠 51735 以保留網頁偏好；被占用時改用空閒埠；--check 一律用空閒埠），
    等 /health 回應後開啟原生視窗（Windows: Edge WebView2；macOS: Cocoa WebKit）。
  * 遠端模式：`--server URL` 或環境變數 ANLA_SERVER_URL，只開視窗連到該伺服器。

其他：
  --check     啟動（或連線）伺服器、呼叫 /health，印出 OK 後以 0 結束；不開任何視窗（CI 煙霧測試用）。
  --browser   不用原生視窗，改開系統瀏覽器（pywebview 不可用時也會自動退回此模式）。
  --no-tray   不建立系統列圖示。

系統列圖示（選用，目前只在 Windows）：安裝 pystray + Pillow 後，原生視窗模式會在通知區域
  顯示圖示，選單有「開啟會客室／在瀏覽器開啟／南投求助專線／結束」；圖示執行中時關閉視窗
  只會縮到系統列，選「結束」才停止本機服務。缺套件、非 Windows、--browser 或 --no-tray 時，
  行為與沒有系統列時相同（關閉視窗即結束）。--check 只檢查元件能否載入，不建立圖示。

資料與祕密：
  * SQLite 放在使用者資料夾（Windows: %APPDATA%\\AnlaYouth；macOS: ~/Library/Application Support/AnlaYouth；
    Linux: $XDG_DATA_HOME/AnlaYouth），透過環境變數 DATABASE_PATH 在匯入 app 之前設定；
    若使用者已自行設定 DATABASE_PATH 則尊重之。
  * LLM_API_KEY（任一家 AI 服務）/ WORKBENCH_PASSWORD 等只從環境變數讀取；本程式不寫入、不封裝任何金鑰。
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

def open_native_window(url: str, use_tray: bool = True) -> bool:
    """以 pywebview 開啟原生視窗；阻塞到視窗關閉（或從系統列選「結束」）。pywebview 不可用時回傳 False。

    pywebview 的 GUI 迴圈一定在主執行緒（webview.start）；系統列圖示在 webview.start 的
    func 執行緒中另開背景執行緒執行（只在 Windows，見 tray_unavailable_reason）。
    """
    try:
        import webview  # pywebview
    except Exception as exc:  # ImportError 或平台後端缺件
        print(f"[資訊] 無法載入 pywebview（{exc}），改用系統瀏覽器。", file=sys.stderr)
        return False

    storage = os.path.join(user_data_dir(), "webview")
    os.makedirs(storage, exist_ok=True)
    tray: TrayController | None = None
    try:
        window = webview.create_window(
            WINDOW_TITLE,
            url,
            width=1100,
            height=800,
            min_size=(380, 600),
            text_select=True,  # 允許複製求助專線等文字
        )
        if use_tray:
            reason = tray_unavailable_reason()
            if reason is None:
                tray = TrayController(webview, window, url)
            else:
                print(f"[資訊] 不使用系統列圖示：{reason}", file=sys.stderr)
        # private_mode=False + storage_path：保留主題偏好等 localStorage；資料只在本機使用者資料夾。
        # func 在 GUI 迴圈啟動後於另一執行緒執行；視窗啟動失敗時不會建立系統列圖示。
        webview.start(func=tray.start if tray else None, private_mode=False, storage_path=storage)
        return True
    except Exception as exc:  # 例如 Windows 缺 WebView2 Runtime
        print(f"[資訊] 原生視窗啟動失敗（{exc}），改用系統瀏覽器。", file=sys.stderr)
        return False
    finally:
        if tray:
            tray.stop()


# ---------------------------------------------------------------------------
# 系統列圖示（Windows 通知區域；選用）
# ---------------------------------------------------------------------------

# 與 static/offline.html「需要人陪的時候」一致。
HELPLINES = (
    ("119", "緊急救護"),
    ("110", "報案"),
    ("1925", "安心專線（24 小時）"),
    ("1995", "生命線（24 小時）"),
    ("1980", "張老師"),
)
TRAY_ICON_SIZE = 64


def tray_unavailable_reason() -> str | None:
    """可以使用系統列圖示時回傳 None，否則回傳原因（只匯入、不建立任何視窗或圖示）。

    * Windows：pystray 的 win32 後端可在任意執行緒執行自己的訊息迴圈，可與 pywebview 並存。
    * macOS：pystray（NSStatusItem）與 pywebview（Cocoa）都必須占用主執行緒的 NSApplication
      迴圈，pystray 的 run_detached 需要共用 pywebview 內部的 NSApplication，目前無法安全整合，停用。
    * Linux：pywebview（GTK/Qt）與 pystray（AppIndicator/GTK/Xorg）的迴圈整合未經驗證，停用。
    """
    if not sys.platform.startswith("win"):
        return "目前只在 Windows 啟用（macOS／Linux 的 GUI 迴圈無法與 pywebview 安全並存）"
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception as exc:  # ImportError，或 pystray 後端載入失敗
        return f"未安裝 pystray／Pillow（{exc}）"
    return None


def load_tray_image():
    """系統列圖示：優先用 static/icons/icon-192.png，讀不到就用程式畫一個簡單圖示。"""
    from PIL import Image, ImageDraw

    size = (TRAY_ICON_SIZE, TRAY_ICON_SIZE)
    path = os.path.join(resource_root(), "static", "icons", "icon-192.png")
    try:
        with Image.open(path) as img:
            return img.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
    except Exception as exc:
        print(f"[資訊] 讀不到圖示 {path}（{exc}），改用內建圖示。", file=sys.stderr)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((2, 2, 61, 61), fill=(38, 120, 110, 255))
    draw.ellipse((20, 18, 44, 42), fill=(255, 255, 255, 255))
    draw.rectangle((29, 40, 35, 50), fill=(255, 255, 255, 255))
    return img


class TrayController:
    """系統列圖示與「關閉視窗＝縮到系統列」行為。

    執行緒：
      * webview.start() 佔用主執行緒；start() 由 pywebview 在 func 執行緒呼叫，再另開 daemon
        執行緒跑 pystray 的訊息迴圈（Windows 允許非主執行緒）。
      * 選單回呼在 pystray 執行緒執行；pywebview 的 window.show/hide/destroy 會 Invoke 到 GUI 執行緒，
        可安全跨執行緒呼叫。
      * closing 事件在 GUI 執行緒同步執行，處理函式不可阻塞，所以隱藏視窗另開執行緒處理。
    """

    def __init__(self, webview_module, window, url: str) -> None:
        self.webview = webview_module
        self.window = window
        self.url = url.rstrip("/")
        self.icon = None
        self.help_window = None
        self.running = threading.Event()
        self.quitting = False
        self._minimized = False
        self._notified = False
        self._lock = threading.Lock()

        window.events.closing += self._on_closing
        window.events.minimized += self._on_minimized
        window.events.restored += self._on_restored
        window.events.maximized += self._on_restored
        window.events.shown += self._hook_system_close

    # --- 生命週期 --------------------------------------------------------

    def start(self) -> None:
        """建立圖示並在背景執行緒執行；失敗時只記錄，視窗照常運作（關閉即結束）。"""
        try:
            import pystray

            item = pystray.MenuItem
            helplines = [item(f"{num} {label}", self._action(self.open_help)) for num, label in HELPLINES]
            menu = pystray.Menu(
                item("開啟會客室", self._action(self.show_main), default=True),
                item("在瀏覽器開啟", self._action(self.open_in_browser)),
                item("南投求助專線", pystray.Menu(
                    item("開啟求助專線頁面", self._action(self.open_help)),
                    pystray.Menu.SEPARATOR,
                    *helplines,
                )),
                pystray.Menu.SEPARATOR,
                item("結束", self._action(self.quit)),
            )
            self.icon = pystray.Icon(APP_ID, load_tray_image(), WINDOW_TITLE, menu)
        except Exception as exc:
            print(f"[資訊] 系統列圖示建立失敗（{exc}），關閉視窗即結束程式。", file=sys.stderr)
            self.icon = None
            return
        threading.Thread(target=self._run_icon, name="anla-tray", daemon=True).start()

    def _run_icon(self) -> None:
        def setup(icon) -> None:
            icon.visible = True
            self.running.set()
            print("[資訊] 系統列圖示已啟動。", file=sys.stderr)

        try:
            self.icon.run(setup=setup)
        except Exception as exc:
            print(f"[資訊] 系統列圖示執行失敗（{exc}），關閉視窗即結束程式。", file=sys.stderr)
        finally:
            self.running.clear()
            # 圖示意外消失而視窗仍隱藏時，把視窗叫回來，避免程式在背景「找不到」。
            if not self.quitting:
                self._safe(self.window.show)

    def stop(self) -> None:
        self.quitting = True
        icon, self.icon = self.icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception as exc:
                print(f"[資訊] 關閉系統列圖示時發生錯誤（{exc}）。", file=sys.stderr)
        self.running.clear()

    # --- 視窗事件 --------------------------------------------------------

    def _on_closing(self):
        """回傳 False 取消關閉（改為隱藏）；系統列沒在執行時照舊關閉並結束程式。"""
        if self.quitting or not self.running.is_set():
            return None
        threading.Thread(target=self._hide_to_tray, name="anla-hide", daemon=True).start()
        return False

    def _hide_to_tray(self) -> None:
        time.sleep(0.05)  # 讓 GUI 執行緒先完成 FormClosing（含 _hook_system_close 的判斷）
        if self.quitting:
            return
        self._safe(self.window.hide)
        if not self._notified and self.icon is not None:
            self._notified = True
            try:
                self.icon.notify("會客室仍在系統列執行。按右鍵圖示可重新開啟或選「結束」。", WINDOW_TITLE)
            except Exception:
                pass  # 通知只是提示，失敗不影響功能

    def _on_minimized(self) -> None:
        self._minimized = True

    def _on_restored(self) -> None:
        self._minimized = False

    def _hook_system_close(self) -> None:
        """Windows：登出／關機／工作管理員結束時不要攔截關閉，否則會擋住關機。

        pywebview 的 closing 事件不提供關閉原因，所以另外掛 WinForms 的 FormClosing
        （在 pywebview 自己的處理之後執行），遇到非使用者關閉就取消「隱藏」並正常結束。
        """
        form = getattr(self.window, "native", None)
        if form is None or not sys.platform.startswith("win"):
            return

        def on_form_closing(_sender, args) -> None:
            if str(args.CloseReason) in ("WindowsShutDown", "TaskManagerClosing", "ApplicationExitCall"):
                self.quitting = True
                args.Cancel = False

        try:
            form.FormClosing += on_form_closing
        except Exception as exc:
            print(f"[資訊] 無法監看 Windows 關機事件（{exc}）。", file=sys.stderr)

    # --- 選單動作 --------------------------------------------------------

    def _action(self, func):
        # pystray 依參數個數決定傳入 (icon, item)；這裡一律包成無參數，並吞掉例外避免中斷訊息迴圈。
        def handler(_icon, _item) -> None:
            self._safe(func)

        return handler

    @staticmethod
    def _safe(func) -> None:
        try:
            func()
        except Exception as exc:
            print(f"[資訊] 系統列動作失敗（{getattr(func, '__name__', func)}：{exc}）", file=sys.stderr)

    def show_main(self) -> None:
        self.window.show()
        if self._minimized:
            self.window.restore()  # WinForms 的 restore 會取消最大化，只在最小化時呼叫

    def open_in_browser(self) -> None:
        webbrowser.open(self.url + "/")

    def open_help(self) -> None:
        """在另一個原生小視窗開 /offline（離線求助頁），不打斷會客室的對話；失敗改用瀏覽器。"""
        help_url = self.url + "/offline"
        with self._lock:
            existing = self.help_window
        if existing is not None:
            existing.show()
            return
        try:
            win = self.webview.create_window(
                "南投求助專線", help_url, width=520, height=760, min_size=(360, 480), text_select=True,
            )
        except Exception as exc:
            print(f"[資訊] 無法開啟求助頁視窗（{exc}），改用瀏覽器。", file=sys.stderr)
            webbrowser.open(help_url)
            return

        def on_closed() -> None:
            with self._lock:
                if self.help_window is win:
                    self.help_window = None

        win.events.closed += on_closed
        with self._lock:
            self.help_window = win

    def quit(self) -> None:
        """結束：關閉所有視窗 → webview.start() 返回 → main() 停止本機伺服器。"""
        self.quitting = True
        with self._lock:
            windows = [w for w in (self.help_window, self.window) if w is not None]
        for win in windows:
            self._safe(win.destroy)
        if self.icon is not None:
            self._safe(self.icon.stop)


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
    parser.add_argument("--no-tray", action="store_true",
                        help="不建立系統列圖示（關閉視窗即結束程式）")
    parser.add_argument("--require-tray", action="store_true",
                        help="搭配 --check：系統列元件（pystray／Pillow／圖示）不可用時視為失敗（封裝煙霧測試用）")
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
        if server:
            server.stop()
        # 只檢查系統列元件能否載入（匯入 pystray／Pillow、讀圖示），不建立圖示或視窗。
        tray_problem = "--no-tray" if args.no_tray else tray_unavailable_reason()
        if tray_problem is None:
            try:
                load_tray_image()
            except Exception as exc:
                tray_problem = f"圖示載入失敗（{exc}）"
        tray = "available" if tray_problem is None else "unavailable"
        if args.require_tray and tray_problem is not None:
            print(f"FAIL: 系統列元件不可用：{tray_problem}", file=sys.stderr)
            return 1
        db = os.environ.get("DATABASE_PATH", "") if server else "(remote)"
        print(f"OK mode={mode} url={url} policy={health.get('dialogue_policy', '?')} db={db} tray={tray}")
        return 0

    try:
        if args.browser or not open_native_window(url, use_tray=not args.no_tray):
            open_in_browser_and_wait(url, server)
    finally:
        if server:
            server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
