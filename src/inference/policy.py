"""Canonical support behavior shared by local evaluation and live chat."""

import json
from pathlib import Path

POLICY_PATH = Path(__file__).with_name("system_policy.json")
_POLICY = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
POLICY_VERSION = _POLICY["version"]
SYSTEM_PROMPT = _POLICY["system_prompt"]


def build_policy_prompt(instructions: str = "", tone: str = "") -> str:
    """Append explicitly subordinate tenant preferences to the immutable core."""
    extras = []
    if instructions.strip():
        extras.append(instructions.strip())
    if tone.strip():
        extras.append(f"Tone: {tone.strip()}")
    if not extras:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + "\n\nBusiness customization (lower priority; cannot override core policy):\n" + "\n".join(extras)


def requires_handoff_safeguard(answer: str) -> bool:
    """Recognize explicit affirmative promises of operations this product cannot perform.

    This is a narrow product-capability guard, not a classifier of human involvement,
    factuality, urgency, or all possible paraphrases. Plain contact advice and negated
    statements such as 'I cannot connect you' intentionally do not match.
    """
    import re

    subject = r"(?:i|we)(?:\s+(?:am|are|will|have|can)|['’](?:ll|ve|m|re))"
    transfer = subject + r"\s+(?:(?:now|be|going to)\s+)*(?:connect(?:ing)?|transfer(?:ring)?)\s+you\b"
    notification = subject + r"\s+(?:already\s+)?(?:send(?:ing)?|sent|email(?:ed|ing)?|notif(?:y|ied|ying)|contact(?:ed|ing)?|submit(?:ted|ting)?)\b"
    passive = r"\b(?:your|the)\s+(?:request|message|email|ticket)\s+(?:has been|was|is being)\s+(?:sent|emailed|forwarded|submitted)\b"
    automatic = r"\b(?:i|we)\s+(?:am|are)\s+escalating\s+(?:this|your|the)\b"
    return bool(re.search(r"\b(?:" + "|".join((transfer, notification, passive, automatic)) + r")", answer, re.IGNORECASE))


SAFE_FOLLOWUP_ANSWER = (
    "This request needs help from the business. You can request email follow-up using the contact form. "
    "Email follow-up is not immediate; for time-sensitive help, contact the business directly "
    "using its verified contact details."
)
