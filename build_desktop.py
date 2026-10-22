"""以 PyInstaller 封裝桌面版（one-folder）。

    python build_desktop.py                 # Windows → dist/AnlaYouth/AnlaYouth.exe；macOS → dist/AnlaYouth.app
    python build_desktop.py --dmg           # macOS：另包成 dist/AnlaYouth.dmg（預設 hdiutil）
    python build_desktop.py --installer     # Windows：另呼叫 Inno Setup (ISCC) 產生 dist/AnlaYouth_Setup.exe
    python build_desktop.py --smoke         # 封裝後執行打包版 --check（Windows 且已安裝 pystray 時加 --require-tray）

只封裝 templates/、static/、data/ 與程式碼；不封裝資料庫、.env 或任何 API 金鑰。
需求：pip install -r requirements.txt -r requirements-desktop.txt
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "AnlaYouth"
BUNDLE_ID = "tw.nantou.anlayouth"
DATA_DIRS = ("templates", "static", "data")
# 這些檔案絕不能進入安裝包（資料庫、環境變數檔、金鑰）。
FORBIDDEN_PATTERNS = ("*.db", "*.db-journal", "*.sqlite*", ".env", ".env.*", "*.pem", "*.key", "*.p12")
# 建置產物檢查：第三方套件本來就帶有 *.pem（例如 certifi 的 CA 憑證包），只擋資料庫與 .env。
DIST_FORBIDDEN_PATTERNS = ("*.db", "*.db-journal", "*.db.key", "*.sqlite*", ".env", ".env.*")

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"


def run(cmd: list[str], **kwargs) -> None:
    print("+", " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kwargs)


def find_forbidden(base: str, patterns: tuple[str, ...] = FORBIDDEN_PATTERNS) -> list[str]:
    hits = []
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            if any(fnmatch.fnmatch(name.lower(), pat) for pat in patterns):
                hits.append(os.path.join(dirpath, name))
    return hits


def preflight() -> None:
    for d in DATA_DIRS:
        path = os.path.join(ROOT, d)
        if not os.path.isdir(path):
            sys.exit(f"缺少資料夾：{path}")
        bad = find_forbidden(path)
        if bad:
            sys.exit("下列檔案不可封裝（資料庫／金鑰），請移出後再建置：\n  " + "\n  ".join(bad))
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("找不到 PyInstaller，請先執行：pip install -r requirements-desktop.txt")


def pyinstaller_build(clean: bool) -> str:
    work = os.path.join(ROOT, "build", "pyinstaller")
    dist = os.path.join(ROOT, "dist")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", APP_NAME,
        "--distpath", dist,
        "--workpath", work,
        "--specpath", work,
        "--paths", ROOT,
        # 測試與開發工具不需要進安裝包
        "--exclude-module", "pytest",
        "--exclude-module", "tests",
        "--exclude-module", "tkinter",
    ]
    if clean:
        cmd.append("--clean")
    for d in DATA_DIRS:
        # 放在 _MEIPASS 根目錄，app.py 的 os.path.dirname(__file__) 與 Flask 預設 templates/static 才找得到。
        cmd += ["--add-data", f"{os.path.join(ROOT, d)}{os.pathsep}{d}"]
    if IS_MAC:
        cmd += ["--osx-bundle-identifier", BUNDLE_ID]
    cmd.append(os.path.join(ROOT, "desktop_launcher.py"))
    run(cmd, cwd=ROOT)

    if IS_MAC:
        out = os.path.join(dist, f"{APP_NAME}.app")
    else:
        exe = f"{APP_NAME}.exe" if IS_WIN else APP_NAME
        out = os.path.join(dist, APP_NAME, exe)
    if not os.path.exists(out):
        sys.exit(f"建置後找不到 {out}")
    bad = find_forbidden(os.path.join(dist, f"{APP_NAME}.app" if IS_MAC else APP_NAME), DIST_FORBIDDEN_PATTERNS)
    if bad:
        sys.exit("建置產物含不該封裝的檔案：\n  " + "\n  ".join(bad))
    print(f"建置完成：{out}")
    return out


def executable_path(out: str) -> str:
    if IS_MAC:
        return os.path.join(out, "Contents", "MacOS", APP_NAME)
    return out


def tray_bundled() -> bool:
    """建置環境有 pystray + Pillow 時，PyInstaller（pyinstaller-hooks-contrib 的 hook-pystray）會一併封裝；
    系統列只在 Windows 啟用，所以只有 Windows 需要驗證。"""
    return IS_WIN and all(importlib.util.find_spec(m) is not None for m in ("pystray", "PIL"))


def smoke_test(out: str) -> None:
    exe = executable_path(out)
    cmd = [exe, "--check"]
    if tray_bundled():
        # 只匯入 pystray／Pillow 並讀取圖示，不建立圖示或視窗；缺件時打包版回傳 exit 1。
        cmd.append("--require-tray")
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, DATABASE_PATH=os.path.join(tmp, "smoke.db"))
        # windowed 版沒有主控台；desktop_launcher 會把輸出寫到使用者資料夾的 launcher.log，
        # 這裡以結束代碼判定成敗。
        print("+", " ".join(cmd[1:]), flush=True)
        proc = subprocess.run(cmd, env=env, timeout=120, capture_output=True, text=True)
        print(proc.stdout.strip() or "(打包版無主控台輸出；詳見使用者資料夾 launcher.log)")
        if proc.returncode != 0:
            print(proc.stderr)
            sys.exit(f"打包版 --check 失敗，exit={proc.returncode}")
    print(f"打包版 {' '.join(cmd[1:])} 通過（exit 0）")


def build_dmg(app_path: str, tool: str) -> str:
    dmg = os.path.join(ROOT, "dist", f"{APP_NAME}.dmg")
    stage = os.path.join(ROOT, "build", "dmg")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    if os.path.exists(dmg):
        os.remove(dmg)
    if tool == "create-dmg" and shutil.which("create-dmg"):
        # https://github.com/create-dmg/create-dmg（brew install create-dmg）
        shutil.copytree(app_path, os.path.join(stage, os.path.basename(app_path)), symlinks=True)
        run(["create-dmg", "--volname", APP_NAME, "--app-drop-link", "420", "120",
             "--icon", f"{APP_NAME}.app", "140", "120", dmg, stage])
    else:
        if tool == "create-dmg":
            print("找不到 create-dmg，改用 hdiutil。")
        run(["ditto", app_path, os.path.join(stage, os.path.basename(app_path))])
        os.symlink("/Applications", os.path.join(stage, "Applications"))
        run(["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", stage, "-ov", "-format", "UDZO", dmg])
    print(f"DMG 完成：{dmg}")
    return dmg


def find_iscc() -> str | None:
    found = shutil.which("iscc") or shutil.which("ISCC")
    if found:
        return found
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Inno Setup 6", "ISCC.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Inno Setup 6", "ISCC.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
    ]
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def build_installer(version: str) -> str:
    iscc = find_iscc()
    if not iscc:
        sys.exit("找不到 Inno Setup 6 的 ISCC.exe（choco install innosetup 或 https://jrsoftware.org/isdl.php）")
    run([iscc, f"/DMyAppVersion={version}", os.path.join(ROOT, "packaging", f"{APP_NAME}.iss")])
    out = os.path.join(ROOT, "dist", f"{APP_NAME}_Setup.exe")
    if not os.path.isfile(out):
        sys.exit(f"Inno Setup 執行後找不到 {out}")
    print(f"安裝程式完成：{out}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="封裝少年仔、安啦會客室桌面版")
    parser.add_argument("--no-clean", action="store_true", help="保留 PyInstaller 快取（加快重建）")
    parser.add_argument("--smoke", action="store_true", help="封裝後執行打包版 --check")
    parser.add_argument("--dmg", action="store_true", help="macOS：產生 .dmg")
    parser.add_argument("--dmg-tool", choices=("hdiutil", "create-dmg"), default="hdiutil")
    parser.add_argument("--installer", action="store_true", help="Windows：以 Inno Setup 產生安裝精靈")
    parser.add_argument("--version", default=os.environ.get("ANLA_VERSION", "1.3.0"),
                        help="安裝程式版本號（預設 1.3.0 或環境變數 ANLA_VERSION）")
    args = parser.parse_args()

    preflight()
    out = pyinstaller_build(clean=not args.no_clean)
    if args.smoke:
        smoke_test(out)
    if args.dmg:
        if not IS_MAC:
            sys.exit("--dmg 只能在 macOS 上執行")
        build_dmg(out, args.dmg_tool)
    if args.installer:
        if not IS_WIN:
            sys.exit("--installer 只能在 Windows 上執行")
        build_installer(args.version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
