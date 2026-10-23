# -*- coding: utf-8 -*-
"""Offline stand-in for the AI model (tests and the 9.5 gate only).

Since v2.5.9 every student-facing reply comes from the model (or the reviewed safety text, or an honest outage
notice). Tests that check the conversation pipeline — memory, roles, safety fallbacks, offers — need a model
reply without a network, so they borrow the rule engine as a deterministic stand-in. It says nothing about the
quality of a real model's wording; that has to be checked with a real key.
"""
from unittest.mock import patch

from engine import dialogue_ai
from engine.dialogue_reply import local_reply


def stand_in():
    """Context manager: the model "answers" with the rule engine's reply for this state."""
    return patch.object(dialogue_ai, "MODEL_STAND_IN", local_reply)
