"""Sanity check that the 9.5 gate is not vacuous: break one safeguard at a time, expect the score to drop.

Run from the project root:  .venv/Scripts/python.exe tests/eval_mutation_check.py
Every line should end with caught=YES. A NO means the gate can no longer see that safeguard."""
import os
import re
import sys
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.argv = [sys.argv[0], "--skip-unittests"]
import eval_95_gate as gate  # noqa: E402  (sets up a temp DB on import)
from engine import dialogue_policy, dialogue_reply  # noqa: E402


@contextmanager
def _both(*patches):
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


MUTATIONS = {
    "no PII masking": lambda: patch("engine.dialogue_ai.scrub_pii", lambda text: text),
    "no DB encryption": lambda: _both(patch("models.database.seal", lambda value: value),
                                      patch("engine.referral.seal", lambda value: value)),
    "no IPTS/IMV signals": lambda: _both(patch.object(dialogue_policy, "THWARTED_BELONGING", r"(?!x)x"),
                                         patch.object(dialogue_policy, "PERCEIVED_BURDEN", r"(?!x)x"),
                                         patch.object(dialogue_policy, "ENTRAPMENT", r"(?!x)x")),
    "no third-party detection": lambda: patch.object(dialogue_policy, "THIRD_PARTY", r"(?!x)x"),
    "listen_only ignored": lambda: _both(patch.object(dialogue_reply, "_styled", lambda text, state, message: text),
                                         patch.object(dialogue_policy, "REPLY_STYLES", ("warm",))),
    "no hyperbole masking": lambda: patch("engine.rules.HYPERBOLE_PATTERN", __import__("re").compile(r"(?!x)x")),
}


def score():
    gate.database.init_db()
    _, results = gate.run_all()
    deductions = []
    triage, misses = gate.score_triage(results, deductions)
    total = triage + gate.score_style(results, deductions) + gate.score_evidence(results, deductions) \
        + gate.score_security(results, deductions) + gate.score_platform(results, deductions)
    return round(total, 2), misses, [d[2] for d in deductions]


baseline = score()
print("baseline", baseline[0], baseline[1])
for name, make in MUTATIONS.items():
    # Fresh database per mutation so ciphertext checks are not polluted by earlier runs.
    fresh = os.path.join(gate._TMP.name, re.sub(r"[^A-Za-z0-9]+", "_", name) + ".db")
    with patch.object(gate.Config, "DATABASE_PATH", fresh), patch.object(gate.database, "DB_PATH", fresh), make():
        total, misses, reasons = score()
    print(f"{name:<26} total={total:5.2f} misses={misses} caught={'YES' if total < baseline[0] or misses else 'NO'}")
    for reason in reasons[:3]:
        print("      -", reason)
