"""Shared result types for all guardrails."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Finding:
    """One thing a detector found. Raw matched text is deliberately NOT stored
    (it may be PII); only the span, a type label and a weight are kept."""

    kind: str
    start: int = -1
    end: int = -1
    weight: float = 1.0
    detail: str = ""


@dataclass
class GuardResult:
    guard: str                      # e.g. "pii", "injection", "schema"
    flagged: bool                   # True = the guardrail objected to the content
    action: str = "allow"           # allow | redact | block | refuse | crisis | escalate | disclaimer | regenerate | fallback
    findings: list[Finding] = field(default_factory=list)
    sanitized_text: str | None = None
    score: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def kinds(self) -> list[str]:
        return sorted({f.kind for f in self.findings})

    def summary(self) -> dict[str, Any]:
        return {
            "guard": self.guard,
            "flagged": self.flagged,
            "action": self.action,
            "kinds": self.kinds(),
            "score": None if self.score is None else round(self.score, 3),
        }
