"""Prompt-injection detection: normalisation + weighted rules + noisy-OR score.

Approach
--------
1. Normalise the text (Unicode NFKC, strip zero-width characters, lower-case,
   collapse whitespace) and also build a "de-leeted" copy (1->i, 0->o, ...).
2. Run a set of weighted regex rules for the main attack families:
   instruction override, system-prompt extraction, persona/jailbreak,
   cross-customer / secret exfiltration, fake role delimiters,
   authority claims, and base64-encoded payloads (decoded and re-scanned).
3. Combine rule weights with noisy-OR:  score = 1 - prod(1 - w_i).
   score >= THRESHOLD  ->  block.

Known limitations (see REPORT.md): paraphrased attacks without trigger words,
non-English attacks, homoglyph (e.g. Cyrillic) substitution, multi-turn
attacks, and legitimate text that quotes an attack phrase (false positives).
"""
from __future__ import annotations

import base64
import binascii
import re
import unicodedata

from .types import Finding, GuardResult

THRESHOLD = 0.6

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})

_W = r"(?:\W+\w+){0,5}?"  # up to five filler words

RULES: list[tuple[str, re.Pattern, float]] = [
    ("instruction_override", re.compile(
        r"\b(?:ignore|disregard|forget|override|bypass|discard)\b"
        r"(?:\W+(?:all|any|the|your|my|previous|prior|above|earlier|former|preceding|these|those|safety|system|and|of)){0,5}"
        r"\W+(?:instructions?|rules|prompts?|guidelines|directions|restrictions|polic(?:y|ies)|constraints|safeguards)"
    ), 0.85),
    ("prompt_extraction", re.compile(
        r"\b(?:reveal|show|print|repeat|output|display|tell\s+me|leak|share|give\s+me|recite)\W+(?:me\W+)?"
        r"(?:your|the|ur)\W+(?:system|hidden|initial|original|secret|internal|developer)\W+"
        r"(?:prompt|instructions?|rules|message|configuration)"
        r"|\brepeat\s+(?:everything|all|the\s+text)\s+(?:above|before)\b"
    ), 0.8),
    ("persona_jailbreak", re.compile(
        r"\byou\s+are\s+now\b|\bact\s+as\s+(?:an?\s+)?(?:unrestricted|unfiltered|jailbroken|evil)"
        r"|\bpretend\s+(?:you\s+are|to\s+be|you're)\b|\b(?:developer|dan|god|jailbreak)\s+mode\b"
        r"|\bdo\s+anything\s+now\b|\b(?:without|with\s+no|no)\s+(?:any\s+)?(?:restrictions|filters|guardrails|safety\s+rules)\b"
    ), 0.7),
    ("exfiltration_others", re.compile(
        r"(?:(?:data|accounts?|records?|transactions?|history|balances?|details|information|numbers?)\W+(?:\w+\W+){0,3}?"
        r"(?:of|for|belonging\s+to)\W+(?:\w+\W+){0,2}?(?:other|another|all)\W+(?:customers?|users?|clients?))"
        r"|(?:(?:other|another|all)\W+(?:customers?|users?|clients?)\W*(?:'s|s')?\W+"
        r"(?:data|accounts?|records?|transactions?|history|balances?|details|information))"
    ), 0.75),
    ("exfiltration_secrets", re.compile(
        r"\b(?:api[\s_-]?keys?|secret[\s_-]?keys?|access[\s_-]?tokens?|admin(?:istrator)?\s+password"
        r"|database\s+credentials|internal\s+(?:documents?|notes|tools))\b"
    ), 0.6),
    ("fake_delimiter", re.compile(
        r"</?\s*(?:system|assistant|instructions?|prompt)\s*>|\[/?\s*(?:system|inst)\s*\]"
        r"|##\s*(?:system|instructions?)\b|<\|(?:im_start|im_end|system)\|>"
    ), 0.7),
    ("authority_claim", re.compile(
        r"\bnew\s+(?:instructions?|rules|system\s+prompt)\s*[:\-]"
        r"|\bfrom\s+now\s+on\b[^.]{0,40}\b(?:you\s+(?:must|will|should)|ignore|only|always)"
        r"|\bsystem\s+override\b|\boverride\s+(?:mode|code|protocol)\b"
        r"|\b(?:i\s+am|i'm|this\s+is)\s+(?:the\s+|your\s+|an?\s+)?(?:developer|admin(?:istrator)?|creator|owner|engineer)\b"
    ), 0.5),
]

_B64 = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")
_DECODED_RULES = {"instruction_override", "prompt_extraction", "persona_jailbreak"}


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH).lower()
    return re.sub(r"\s+", " ", t).strip()


def _scan(text: str) -> dict[str, float]:
    hits: dict[str, float] = {}
    for name, pat, weight in RULES:
        if pat.search(text):
            hits[name] = weight
    return hits


def _decode_base64_blobs(text: str) -> list[str]:
    out = []
    for m in _B64.finditer(text):
        blob = m.group()
        pad = "=" * (-len(blob) % 4)
        try:
            raw = base64.b64decode(blob + pad, validate=True)
            decoded = raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if decoded and all(ch.isprintable() or ch.isspace() for ch in decoded):
            out.append(decoded)
    return out


def detect_injection(text: str, threshold: float = THRESHOLD) -> GuardResult:
    norm = normalize(text)
    hits = _scan(norm)
    for name, w in _scan(norm.translate(_LEET)).items():      # leetspeak variants
        hits[name] = max(hits.get(name, 0.0), w)

    # base64 payloads: decode (from the original-case text) and re-scan
    for decoded in _decode_base64_blobs(unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)):
        for name, w in _scan(normalize(decoded)).items():
            if name in _DECODED_RULES:
                hits["encoded_injection"] = max(hits.get("encoded_injection", 0.0), 0.85)

    prod = 1.0
    for w in hits.values():
        prod *= 1.0 - w
    score = 1.0 - prod
    flagged = score >= threshold
    findings = [Finding(name, weight=w) for name, w in sorted(hits.items())]
    return GuardResult(
        guard="injection", flagged=flagged,
        action="block" if flagged else "allow",
        findings=findings, score=score,
        details={"threshold": threshold},
    )
