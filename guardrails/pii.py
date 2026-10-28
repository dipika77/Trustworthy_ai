"""PII detection and redaction (regex + checksum + context rules).

Used twice: on user input (redact before the text reaches the model) and on
model output (redact / block before the text reaches the user).

Approach
--------
* Format-based patterns for emails, Nepali / international phone numbers, SSNs.
* Checksum validation (Luhn) for payment-card numbers, so that long reference
  numbers are not mistaken for cards.
* Context-based patterns for identifiers that have no distinctive format
  (PAN, account number, passport, citizenship number, passwords / OTPs):
  a label such as "account number is" must precede the value.
* Light de-obfuscation for "name [at] domain [dot] com".

Known limitations (see REPORT.md): no names / addresses (no NER), no
spelled-out numbers, no "john at example dot com" without brackets, no
non-Latin scripts, context patterns miss values that appear without a label.
"""
from __future__ import annotations

import re

from .types import Finding

# --- patterns ---------------------------------------------------------------
EMAIL = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])"
)
OBFUSCATED_EMAIL = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9._%+-]+\s*[\[\(\{]\s*at\s*[\]\)\}]\s*[A-Za-z0-9-]+"
    r"(?:\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*[A-Za-z0-9-]+)+",
    re.I,
)
NP_MOBILE = re.compile(r"(?<!\d)(?:\+?977[\s-]?)?9[78]\d[\s-]?\d{3}[\s-]?\d{4}(?!\d)")
INTL_PHONE = re.compile(r"(?<!\w)\+\d{1,3}[\s-]?\(?\d{1,4}\)?(?:[\s-]?\d{2,4}){2,4}(?!\d)")
NP_LANDLINE = re.compile(r"(?<![\d-])0\d{1,2}[\s-]\d{6,7}(?!\d)")
CARD_CANDIDATE = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
CITIZENSHIP_FORMAT = re.compile(r"(?<!\d)\d{2}-\d{2}-\d{2}-\d{5}(?!\d)")
CITIZENSHIP_CONTEXT = re.compile(
    r"citizenship\s*(?:certificate\s*)?(?:no\.?|number|num|#)\s*(?:is|:)?\s*([A-Za-z0-9/-]{5,})", re.I
)
PAN_CONTEXT = re.compile(r"\bPAN\b(?:\s*(?:no\.?|number|#))?\s*(?:is|:)?\s*(\d{9})(?!\d)", re.I)
ACCOUNT_CONTEXT = re.compile(
    r"account\s*(?:no\.?|number|num|#)\s*(?:is|:)?\s*(\d[\d -]{6,22}\d)", re.I
)
PASSPORT_CONTEXT = re.compile(
    r"passport\s*(?:no\.?|number|#)?\s*(?:is|:)?\s*([A-Z]{0,2}\d{6,9})(?!\d)", re.I
)
CREDENTIAL_CONTEXT = re.compile(
    r"\b(?:password|passcode|pin|otp|one[- ]time\s+(?:code|password))\s*(?:is|was|:|=)\s*([^\s,;]{3,})",
    re.I,
)

# Higher number wins when two detections overlap.
PRIORITY = {
    "credential": 9, "card": 8, "ssn": 7, "citizenship_id": 6, "pan": 5,
    "account_number": 4, "passport": 3, "email": 2, "phone": 1,
}
PLACEHOLDER = {
    "credential": "[CREDENTIAL]", "card": "[CARD]", "ssn": "[SSN]",
    "citizenship_id": "[CITIZENSHIP_ID]", "pan": "[PAN]", "account_number": "[ACCOUNT_NO]",
    "passport": "[PASSPORT]", "email": "[EMAIL]", "phone": "[PHONE]",
}
# Categories that must never be "redacted and delivered" on the output side.
HIGH_RISK_KINDS = {"card", "credential", "ssn", "citizenship_id", "pan", "account_number", "passport"}


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _norm_contact(s: str) -> str:
    return re.sub(r"[^a-z0-9@.]", "", s.lower())


def detect_pii(text: str, allowlist: tuple[str, ...] = ()) -> list[Finding]:
    """Return non-overlapping PII findings. `allowlist` holds public values
    (e.g. the company's own support email / hotline) that must not be flagged."""
    allowed = {_norm_contact(a) for a in allowlist}
    cands: list[Finding] = []

    def add(kind: str, m: re.Match, group: int = 0) -> None:
        s, e = m.span(group)
        if _norm_contact(text[s:e]) in allowed:
            return
        cands.append(Finding(kind, s, e))

    for m in EMAIL.finditer(text):
        add("email", m)
    for m in OBFUSCATED_EMAIL.finditer(text):
        add("email", m)
    for pat in (NP_MOBILE, INTL_PHONE, NP_LANDLINE):
        for m in pat.finditer(text):
            add("phone", m)
    for m in CARD_CANDIDATE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            add("card", m)
    for m in SSN.finditer(text):
        add("ssn", m)
    for m in CITIZENSHIP_FORMAT.finditer(text):
        add("citizenship_id", m)
    for m in CITIZENSHIP_CONTEXT.finditer(text):
        add("citizenship_id", m, 1)
    for m in PAN_CONTEXT.finditer(text):
        add("pan", m, 1)
    for m in ACCOUNT_CONTEXT.finditer(text):
        add("account_number", m, 1)
    for m in PASSPORT_CONTEXT.finditer(text):
        add("passport", m, 1)
    for m in CREDENTIAL_CONTEXT.finditer(text):
        value = m.group(1)
        if re.search(r"[^A-Za-z]", value):      # "password is required" is not a credential
            add("credential", m, 1)

    # resolve overlaps: higher priority first, then longer span
    cands.sort(key=lambda f: (-PRIORITY[f.kind], -(f.end - f.start), f.start))
    accepted: list[Finding] = []
    for f in cands:
        if all(f.end <= a.start or f.start >= a.end for a in accepted):
            accepted.append(f)
    accepted.sort(key=lambda f: f.start)
    return accepted


def redact(text: str, findings: list[Finding]) -> str:
    out, pos = [], 0
    for f in sorted(findings, key=lambda f: f.start):
        out.append(text[pos:f.start])
        out.append(PLACEHOLDER[f.kind])
        pos = f.end
    out.append(text[pos:])
    return "".join(out)
