# -*- coding: utf-8 -*-
"""Shared test checks."""
from engine.referral import AUTO_ALERT_ALIAS, AUTO_ALERT_STATUS
from models import database


def consented_cases():
    """Cases the student agreed to share. Since v2.7 orange/red also create an automatic safety alert before
    consent (proposal: 中高風險進入真人工作臺); such an alert must carry no identity, contact or transcript."""
    cases = database.get_all_cases()
    for case in cases:
        if not case["summary"].get("student_consent"):
            assert case["status"] == AUTO_ALERT_STATUS or case["summary"].get("auto_alert"), case["status"]
            assert case["student_alias"] == AUTO_ALERT_ALIAS and not case["student_email"], case["student_alias"]
            assert "transcript" not in case["summary"]
            assert set(case["summary"].get("student_profile", {})) <= {"township"}
    return [case for case in cases if case["summary"].get("student_consent")]
