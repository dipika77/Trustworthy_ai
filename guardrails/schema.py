"""Output schema validation (pure Python, strict).

Required response shape (all fields required, no extra fields):

    {
      "answer":         str,   1..600 characters after stripping
      "category":       str,   one of ALLOWED_CATEGORIES
      "confidence":     float, finite, 0.0 <= x <= 1.0   (bool is NOT accepted)
      "sources":        list[str], each "KB-###", no duplicates;
                        may be empty only when requires_human is true
      "requires_human": bool   (int 0/1 or "true" strings are NOT accepted)
    }

A reply wrapped in a ```json fence is accepted but marked as "repaired".
Anything else that is not valid JSON is rejected.

Limitation: validates structure and types only. A reply can be perfectly
valid and still be wrong, unsafe or ungrounded - that is what the other
output guardrails are for.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

from .types import Finding, GuardResult

ALLOWED_CATEGORIES = {"account", "transfers", "fees", "kyc", "refunds", "security", "general", "escalation"}
REQUIRED = {"answer", "category", "confidence", "sources", "requires_human"}
SOURCE_ID = re.compile(r"^KB-\d{3}$")
MAX_ANSWER_CHARS = 600
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S | re.I)


def parse_output(raw: str) -> tuple[Any, list[str], bool]:
    """Return (object_or_None, errors, repaired)."""
    repaired = False
    text = raw if isinstance(raw, str) else ""
    m = _FENCE.match(text)
    if m:
        text, repaired = m.group(1), True
    try:
        return json.loads(text), [], repaired
    except (json.JSONDecodeError, TypeError) as exc:
        return None, [f"not valid JSON: {exc.__class__.__name__}"], repaired


def validate_object(obj: Any) -> list[str]:
    if not isinstance(obj, dict):
        return ["top-level value must be a JSON object"]
    errors: list[str] = []
    missing = REQUIRED - obj.keys()
    extra = obj.keys() - REQUIRED
    if missing:
        errors.append(f"missing fields: {sorted(missing)}")
    if extra:
        errors.append(f"unexpected fields: {sorted(extra)}")

    if "answer" in obj:
        a = obj["answer"]
        if not isinstance(a, str):
            errors.append("answer must be a string")
        elif not (1 <= len(a.strip()) <= MAX_ANSWER_CHARS):
            errors.append(f"answer length must be 1..{MAX_ANSWER_CHARS} characters")
    if "category" in obj:
        c = obj["category"]
        if not isinstance(c, str) or c not in ALLOWED_CATEGORIES:
            errors.append("category must be one of the allowed values")
    if "confidence" in obj:
        v = obj["confidence"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            errors.append("confidence must be a number")
        elif not math.isfinite(v) or not (0.0 <= v <= 1.0):
            errors.append("confidence must be within 0.0..1.0")
    if "requires_human" in obj and not isinstance(obj["requires_human"], bool):
        errors.append("requires_human must be a boolean")
    if "sources" in obj:
        s = obj["sources"]
        if not isinstance(s, list) or not all(isinstance(x, str) and SOURCE_ID.match(x) for x in s):
            errors.append("sources must be a list of ids like 'KB-001'")
        else:
            if len(set(s)) != len(s):
                errors.append("sources must not contain duplicates")
            if not s and obj.get("requires_human") is not True:
                errors.append("sources may be empty only when requires_human is true")
    return errors


def check_schema(raw: str) -> GuardResult:
    obj, errors, repaired = parse_output(raw)
    if obj is not None:
        errors = validate_object(obj)
    flagged = bool(errors)
    return GuardResult(
        guard="schema", flagged=flagged,
        action="regenerate" if flagged else "allow",
        findings=[Finding("schema_error", detail=e) for e in errors],
        details={"errors": errors, "repaired": repaired, "object": None if flagged else obj},
    )
