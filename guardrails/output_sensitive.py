"""Sensitive-information detection on model output.

Checks, in order of severity:
 1. Secrets / internal material  -> action "block"  (never redact-and-deliver):
    API keys, private keys, bearer tokens, internal hostnames, "INTERNAL ONLY"
    markers, system-prompt leakage phrases and the canary token planted in the
    system prompt.
 2. High-risk PII (card, credentials, government IDs, account numbers)
    -> action "block".
 3. Low-risk PII (e-mail, phone) -> action "redact" (placeholder substituted).
 Public company contact details (PUBLIC_CONTACTS) are allow-listed.

Known limitations (see REPORT.md): regex only, so names, postal addresses and
free-text personal facts are not detected; secrets in unknown formats pass.
"""
from __future__ import annotations

import re

from .knowledge_base import PUBLIC_CONTACTS
from .pii import HIGH_RISK_KINDS, detect_pii, redact
from .types import Finding, GuardResult

CANARY = "CANARY-7f3a9c21"   # planted in the system prompt; must never appear in output

SECRET_RULES: list[tuple[str, re.Pattern]] = [
    ("canary_token", re.compile(re.escape(CANARY), re.I)),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b|\bAKIA[0-9A-Z]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}")),
    ("key_value_secret", re.compile(r"\b(?:api[_-]?key|secret|token)\s*[:=]\s*\S{8,}", re.I)),
    ("internal_host", re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.internal(?:\.[\w-]+)*\b", re.I)),
    ("internal_marker", re.compile(r"\bINTERNAL\s+ONLY\b|\bCONFIDENTIAL\b", re.I)),
    ("system_prompt_leak", re.compile(
        r"\b(?:my|the)\s+system\s+prompt\b|\bmy\s+(?:hidden\s+)?instructions\s+(?:are|say|state)\b"
        r"|\bas\s+instructed\s+in\s+my\s+prompt\b", re.I)),
]


def check_output_sensitive(text: str) -> GuardResult:
    secrets: list[Finding] = []
    for name, pat in SECRET_RULES:
        for m in pat.finditer(text):
            secrets.append(Finding(name, m.start(), m.end()))
    pii = detect_pii(text, allowlist=PUBLIC_CONTACTS)
    findings = secrets + pii

    if not findings:
        return GuardResult("output_sensitive", False, "allow")

    high_risk_pii = any(f.kind in HIGH_RISK_KINDS for f in pii)
    if secrets or high_risk_pii:
        return GuardResult("output_sensitive", True, "block", findings,
                           details={"reason": "secret_or_high_risk_pii"})
    return GuardResult("output_sensitive", True, "redact", findings,
                       sanitized_text=redact(text, pii), details={"reason": "low_risk_pii"})
