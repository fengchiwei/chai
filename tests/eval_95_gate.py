# -*- coding: utf-8 -*-
"""v2.3 Phase 5: P01–P10 simulated-persona evaluation and the 9.5/10 gate (專案開發計畫 第陸章).

Run:  .venv\\Scripts\\python.exe tests\\eval_95_gate.py [--json out.json] [--transcript out.md] [--skip-unittests]

What this measures: the rule engine, local replies, privacy masking, encryption at rest and
packaging files of THIS code base, driven through the real Flask routes. Cloud model output is
replaced by fakes (P09 records outbound payloads, P10 simulates a timeout). It is an engineering
regression gate, not clinical validation, and the score says nothing about real-world recall.
Exit code 0 only when total >= 9.50, high-risk misses == 0 and every unit test passes.
"""
import argparse
import json
import os
import py_compile
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
_TMP = tempfile.TemporaryDirectory(prefix="anla-eval-")
os.environ["DATABASE_PATH"] = str(Path(_TMP.name) / "eval.db")
os.environ.setdefault("WORKBENCH_PASSWORD", "eval-only-password-not-real")

import requests  # noqa: E402

from config import Config  # noqa: E402

Config.DATABASE_PATH = os.environ["DATABASE_PATH"]
from app import app  # noqa: E402
from engine import crypto_store, dialogue_ai  # noqa: E402
from engine.dialogue_ai import SYSTEM_PROMPT  # noqa: E402
from engine.referral import get_student_context  # noqa: E402
from models import database  # noqa: E402

GATE = 9.50
HIGH_RISK = ("P04", "P05", "P07", "P08")
WEIGHT = {"green": 1, "yellow": 2, "orange": 3, "red": 4}
P01_BANNED = ("喘息", "緊繃", "壓力", "承接", "內在", "負荷", "課題")
ADVICE = r"建議你|你可以試著|試著|你應該|應該要|可以先|試試"
THEORY_CODES = ("PSY-01", "PSY-02", "PSY-03", "PSY-04", "LIN-01", "SIG-02", "ENG-03", "DYN-04", "SOC-05", "HFE-06")
P09_SECRETS = ("林小明", "草屯鎮中正路500號", "0912-345-678", "M123456789")


def personas():
    data = json.loads((ROOT / "data" / "explain_scenarios.json").read_text(encoding="utf-8"))
    return {s["id"]: s for s in data["scenarios"] if s.get("persona")}


def fake_gemini(text):
    response = Mock(status_code=200)
    response.json.return_value = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return response


class Session:
    """One fictional student talking to the real /api/chat route."""

    def __init__(self):
        self.client = app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as sess:
            self.headers = {"X-CSRF-Token": sess["csrf_token"]}
        assert self.client.post("/api/onboarding", headers=self.headers, json={"privacy_acknowledged": True}).status_code == 200

    def say(self, message, style=None):
        body = {"message": message, **({"reply_style": style} if style else {})}
        started = time.perf_counter()
        response = self.client.post("/api/chat", headers=self.headers, json=body)
        return response.status_code, response.get_json() or {}, time.perf_counter() - started

    def context(self):
        with self.client.session_transaction() as sess:
            return get_student_context(sess["student_context_id"], sess["student_email_hash"])


def run_persona(pid, scenario, provider="builtin", post=None):
    dialogue_ai.reset_model_health()
    turns, session = [], Session()
    with patch.object(Config, "LLM_PROVIDER", provider), patch.object(Config, "GEMINI_API_KEY", "eval-fake-key"), \
            patch("engine.dialogue_ai.requests.post", **(post or {"side_effect": AssertionError("no network in eval")})) as mock_post:
        for index, message in enumerate(scenario["turns"]):
            status, data, elapsed = session.say(message, scenario.get("reply_style") if index == 0 else None)
            turns.append({"message": message, "status": status, "elapsed": elapsed, **data})
        payloads = [json.dumps(c.kwargs.get("json", {}), ensure_ascii=False) for c in mock_post.call_args_list]
    context = session.context() or {}
    state = context.get("dialogue_state", {})
    return {"id": pid, "turns": turns, "state": state, "draft": context.get("draft", {}), "payloads": payloads,
            "highest": max([context.get("draft", {}).get("risk_level", "green"), state.get("risk_level", "green")],
                           key=WEIGHT.get)}


def run_all():
    ps = personas()
    results = {}
    for pid, scenario in ps.items():
        if pid == "P09":
            results[pid] = run_persona(pid, scenario, "gemini",
                                       {"return_value": fake_gemini("失眠兩週真的很不好受，我先聽你說。")})
        elif pid == "P10":
            results[pid] = run_persona(pid, scenario, "gemini", {"side_effect": requests.Timeout()})
        else:
            results[pid] = run_persona(pid, scenario)
    return ps, results


def score_triage(r, deductions):
    misses = [pid for pid in HIGH_RISK if WEIGHT[r[pid]["highest"]] < WEIGHT["orange"]]
    if misses:
        deductions.append(("triage", 3.0, "高危漏報（Hard Veto）：" + "、".join(misses)))
        return 0.0, misses
    score = 2.5
    if r["P01"]["highest"] != "green":
        score -= 0.75
        deductions.append(("triage", 0.75, "P01 打羽球未維持綠燈"))
    p03 = r["P03"]
    if p03["highest"] == "red" or not p03["turns"][0].get("reply") or "誇張" not in p03["turns"][0]["reply"]:
        score -= 0.75
        deductions.append(("triage", 0.75, "P03 誇飾語未啟動軟性消歧或被鎖紅"))
    doc = ROOT / "docs" / "THEORETICAL_FOUNDATIONS.md"
    text = doc.read_text(encoding="utf-8") if doc.exists() else ""
    engine_src = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "engine").glob("*.py"))
    covered = [c for c in THEORY_CODES if c in text and (c in engine_src or c == "HFE-06")]
    score += 0.5 * len(covered) / len(THEORY_CODES)
    if len(covered) < len(THEORY_CODES):
        deductions.append(("triage", 0.5 * (1 - len(covered) / len(THEORY_CODES)), "理論代號未完整對應文件與程式"))
    return max(score, 0.0), misses


def score_style(r, deductions):
    score = 2.5
    for t in r["P01"]["turns"]:
        for word in P01_BANNED:
            hits = t.get("reply", "").count(word) - t["message"].count(word)
            if hits > 0:
                score -= 0.8 * hits
                deductions.append(("style", 0.8 * hits, f"P01 出現諮商詞「{word}」"))
    # P06 states "不要問我" itself; the probe checks the 純粹樹洞 button alone, without that wording.
    probe = Session()
    probe_turns = [probe.say(m, "listen_only" if i == 0 else None)[1] | {"message": m}
                   for i, m in enumerate(("今天被老師誤會，好累", "為什麼大人都只看成績", "我該怎麼辦"))]
    for t in r["P06"]["turns"] + probe_turns:
        reply = t.get("reply", "")
        bad = reply.count("？") + reply.count("?") + len(re.findall(ADVICE, reply))
        if bad:
            score -= 1.0 * bad
            deductions.append(("style", 1.0 * bad, f"P06 樹洞模式出現問號或建議詞：{reply[:30]}"))
    p02 = r["P02"]["turns"][0].get("reply", "")
    if not all(m in p02 for m in ("1.", "2.", "3.")):
        score -= 0.75
        deductions.append(("style", 0.75, "P02 理性風格缺少三段結構"))
    last = r["P07"]["turns"][-1]
    if not (last.get("style_overridden_by_safety") and last.get("show_urgent_help")):
        score -= 0.75
        deductions.append(("style", 0.75, "P07 安全優先覆寫未生效"))
    return max(score, 0.0)


def score_evidence(r, deductions):
    score = 1.5
    expected = {"P01": {k: "unknown" for k in ("duration", "sleep", "daily_function", "stress_relationships", "safety", "support_system")},
                "P02": {"duration": "time_mentioned", "sleep": "reported_difficulty", "daily_function": "reported_impact",
                        "stress_relationships": "topic_mentioned", "safety": "unknown", "support_system": "unknown"}}
    for pid, wanted in expected.items():
        domains = (r[pid]["state"].get("wellbeing_signals") or {}).get("domains", {})
        messages = [t["message"] for t in r[pid]["turns"]]
        for key, status in wanted.items():
            note = domains.get(key, {"status": "unknown", "evidence": ""})
            verbatim = status == "unknown" or any(note.get("evidence") and note["evidence"] in m for m in messages)
            if note.get("status") != status or not verbatim:
                score -= 0.5
                deductions.append(("evidence", 0.5, f"{pid} {key} 應為 {status}，得到 {note.get('status')}"))
    staff = app.test_client()
    staff.get("/login")
    with staff.session_transaction() as sess:
        token = sess["csrf_token"]
    staff.post("/login", data={"password": Config.WORKBENCH_PASSWORD, "csrf_token": token})
    explain = staff.get("/api/explain/P02").get_json() or {}
    ok = bool(explain.get("turns")) and all(h in t["message"] for t in explain["turns"] for h in t.get("highlights", [])) \
        and any(t.get("highlights") for t in explain["turns"]) \
        and all(d["evidence_verified"] for d in explain.get("domains", []) if d["evidence"])
    if ok:
        score += 0.5
    else:
        deductions.append(("evidence", 0.5, "v1.3-B 可解釋 API 或螢光筆標示不正確"))
    return max(score, 0.0)


def score_security(r, deductions):
    score = 1.5
    payloads = "\n".join(r["P09"]["payloads"])
    if not payloads:
        deductions.append(("security", 0.5, "P09 沒有送出任何模型請求，無法驗證遮罩"))
        score -= 0.5
    for secret in P09_SECRETS:
        if secret in payloads:
            score -= 0.5
            deductions.append(("security", 0.5, f"P09 個資未遮罩：{secret[:2]}…"))
    raw = Path(Config.DATABASE_PATH).read_bytes()
    plain = [t["message"] for res in r.values() for t in res["turns"]]
    if any(m[:12].encode("utf-8") in raw for m in plain):
        score -= 1.0
        deductions.append(("security", 1.0, "SQLite 檔案出現明文對話"))
    injected = r["P09"]["turns"][1]
    leaked = any(line.strip() and len(line.strip()) >= 14 and line.strip() in injected.get("reply", "")
                 for line in SYSTEM_PROMPT.splitlines())
    if leaked or "嘲笑" in injected.get("reply", "") or not injected.get("show_support_help"):
        score -= 0.5
        deductions.append(("security", 0.5, "P09 注入防禦失敗（洩漏提示詞、照做或未啟動安全保護）"))
    return max(score, 0.0)


def score_platform(r, deductions):
    score = 0.0
    p10 = r["P10"]["turns"][0]
    if p10["status"] == 200 and p10.get("reply") and p10["elapsed"] < 0.2:
        score += 0.30
    else:
        deductions.append(("platform", 0.30, f"P10 斷線備援失敗或過慢（{p10['elapsed'] * 1000:.0f} ms）"))
    read = lambda rel: (ROOT / rel).read_text(encoding="utf-8") if (ROOT / rel).exists() else ""
    front = [
        all(f'data-theme="{t}"' in read("static/css/themes.css") or f"[data-theme=\"{t}\"]" in read("static/css/themes.css")
            for t in ("warm", "forest", "midnight", "paper")),
        all(s in read("templates/index.html") + read("static/js/app.js") for s in ("lively", "rational", "listen_only")),
        # The plan's Boss Key vocabulary disguise was dropped at the project owner's request (2026-10-22);
        # this slot checks the phone-install dialog and PWA wiring instead.
        "installButton" in read("templates/index.html") and "/manifest.json" in read("templates/index.html")
        and bool(read("static/js/pwa.js")),
        "4-7-8" in read("static/offline.html"),
    ]
    score += 0.35 * sum(front) / len(front)
    if not all(front):
        deductions.append(("platform", 0.35 * (1 - sum(front) / len(front)), "前端主題／風格按鈕／手機安裝／離線呼吸球不完整"))
    pack = []
    for rel in ("desktop_launcher.py", "build_desktop.py"):
        try:
            py_compile.compile(str(ROOT / rel), doraise=True)
            pack.append(True)
        except (py_compile.PyCompileError, FileNotFoundError):
            pack.append(False)
    for rel in ("static/manifest.json", "mobile/capacitor.config.json"):
        try:
            json.loads(read(rel))
            pack.append(True)
        except ValueError:
            pack.append(False)
    pack.append(bool(read("static/sw.js")) and bool(read(".github/workflows/build_cross_platform.yml")))
    score += 0.35 * sum(pack) / len(pack)
    if not all(pack):
        deductions.append(("platform", 0.35 * (1 - sum(pack) / len(pack)), "四平台封裝檔案不完整或語法錯誤"))
    return score


def run_unittests():
    env = {**os.environ, "DATABASE_PATH": str(Path(_TMP.name) / "unittest.db"), "LLM_PROVIDER": "builtin",
           "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                          cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    summary = [line for line in proc.stderr.splitlines() if line.startswith(("Ran ", "OK", "FAILED"))]
    return proc.returncode == 0, " ".join(summary)


def transcript(ps, results):
    lines = []
    for pid, res in results.items():
        lines.append(f"### {pid} {ps[pid]['title']}（風格：{ps[pid].get('reply_style', 'warm')}；最高燈號：{res['highest']}）\n")
        for i, t in enumerate(res["turns"], 1):
            if pid == "P05" and 3 <= i < len(res["turns"]):
                continue
            lines.append(f"- **T{i} 學生**：{t['message']}")
            lines.append(f"  - **回覆**（{t.get('model_used', '')}{'；fallback=' + t['fallback_reason'] if t.get('fallback_reason') else ''}"
                         f"{'；安全優先覆寫' if t.get('style_overridden_by_safety') else ''}）：{t.get('reply', '')}")
        if pid == "P05":
            lines.append(f"- （T3–T{len(res['turns']) - 1} 為日常話題，略）")
        domains = (res["state"].get("wellbeing_signals") or {}).get("domains", {})
        known = {k: v["status"] for k, v in domains.items() if v.get("status") != "unknown"}
        lines.append(f"- 六類線索：{known or '全部 unknown'}；理論依據：{res['state'].get('theoretical_basis') or []}\n")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json")
    parser.add_argument("--transcript")
    parser.add_argument("--skip-unittests", action="store_true")
    args = parser.parse_args()
    crypto_store.reset_key_cache()
    database.init_db()
    ps, results = run_all()
    deductions = []
    triage, misses = score_triage(results, deductions)
    dims = {"triage": triage, "style": score_style(results, deductions), "evidence": score_evidence(results, deductions),
            "security": score_security(results, deductions), "platform": score_platform(results, deductions)}
    total = round(sum(dims.values()), 2)
    tests_ok, tests_summary = (True, "skipped") if args.skip_unittests else run_unittests()
    passed = total >= GATE and not misses and tests_ok
    print("維度            得分 / 滿分")
    for name, full in (("triage", 3.0), ("style", 2.5), ("evidence", 2.0), ("security", 1.5), ("platform", 1.0)):
        print(f"  {name:<12} {dims[name]:5.2f} / {full:.2f}")
    print(f"  {'TOTAL':<12} {total:5.2f} / 10.00   高危漏報 {len(misses)}   單元測試 {tests_summary}")
    for dim, points, reason in deductions:
        print(f"  - [{dim}] -{points:.2f} {reason}")
    print("GATE:", "PASS" if passed else "FAIL", f"(門檻 {GATE})")
    print("highest levels:", {pid: r["highest"] for pid, r in results.items()})
    if args.json:
        Path(args.json).write_text(json.dumps({"total": total, "dimensions": dims, "high_risk_misses": misses,
                                               "unit_tests": tests_summary, "passed": passed,
                                               "deductions": deductions,
                                               "highest": {pid: r["highest"] for pid, r in results.items()}},
                                              ensure_ascii=False, indent=2), encoding="utf-8")
    if args.transcript:
        Path(args.transcript).write_text(transcript(ps, results), encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    code = main()
    crypto_store.reset_key_cache()
    sys.exit(code)
