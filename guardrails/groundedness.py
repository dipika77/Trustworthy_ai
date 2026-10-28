"""Groundedness validation: is every factual claim supported by the references?

Approach (deliberately simple, dependency-free, explainable)
-----------------------------------------------------------
1. Split the answer into sentences; drop non-claims (greetings, offers of help,
   abstentions such as "I couldn't find that", very short fragments).
2. For each claim compute *lexical coverage*: the share of the claim's content
   stems that appear in the best-matching reference sentence (or pair of
   adjacent sentences).  Coverage >= SUPPORT_THRESHOLD is required.
3. Numeric check: every number in the claim must appear in the references.
4. Polarity check: if the claim and its best-matching reference sentence
   disagree on negation ("not", "never", ...), the claim is treated as
   contradicted.
5. Citation check: every cited source id must be one of the references that
   were actually provided.

Known limitations (see REPORT.md): this is lexical, not semantic.
 * Paraphrases with different vocabulary are wrongly rejected (false positive).
 * Claims that reuse the reference's words but change the meaning
   (swapped subjects, added qualifiers) can pass (false negative).
 * Only negation polarity is checked, not other contradictions.
A production system should use an NLI / entailment model or LLM-as-judge
on top of (not instead of) these cheap checks.
"""
from __future__ import annotations

import re

from .types import Finding, GuardResult

SUPPORT_THRESHOLD = 0.7
MIN_CONTENT_TOKENS = 3

_STOP = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "it", "its", "this", "that", "these", "those",
    "to", "of", "in", "on", "for", "and", "or", "as", "at", "by", "with", "from", "you", "your", "we", "our",
    "they", "them", "their", "will", "can", "may", "per", "up", "any", "so", "if", "then", "than", "also",
    "i", "me", "my", "have", "has", "do", "does", "t", "s",
}
_NEG = {"not", "no", "never", "cannot", "cant", "wont", "doesnt", "isnt", "arent", "dont", "didnt",
        "without", "none", "nor", "neither"}
_NON_CLAIM = re.compile(
    r"^(?:hi|hello|hey|thanks|thank\s+you|happy\s+to\s+help|glad|sure|of\s+course|sorry|apologi[sz]e|"
    r"please\s+(?:contact|reach|call|visit|email|let)|let\s+me\s+know|is\s+there\s+anything|"
    r"i\s+(?:can(?:not|'?t)|couldn'?t|could\s+not|don'?t|do\s+not|am\s+unable|am\s+not\s+able)|"
    r"here\s+is\s+what|here'?s\s+what|i'?ll\s+(?:connect|pass|forward)|i\s+will\s+(?:connect|pass|forward))",
    re.I,
)


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _prep(text: str) -> str:
    text = text.lower().replace("'", "").replace("’", "")
    return re.sub(r"(?<=\d),(?=\d{3})", "", text)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+|\d+(?:\.\d+)?", _prep(text))


def _content(text: str) -> list[str]:
    return [_stem(w) for w in _words(text) if w not in _STOP and w not in _NEG]


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", _prep(text)))


def _negated(text: str) -> bool:
    return any(w in _NEG for w in _words(text))


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def extract_claims(answer: str) -> list[str]:
    claims = []
    for s in split_sentences(answer):
        if s.endswith("?") or _NON_CLAIM.match(s):
            continue
        if len(_content(s)) < MIN_CONTENT_TOKENS:
            continue
        claims.append(s)
    return claims


def _windows(passage: str) -> list[str]:
    sents = split_sentences(passage)
    wins = list(sents)
    wins += [sents[i] + " " + sents[i + 1] for i in range(len(sents) - 1)]
    return wins


def check_groundedness(answer: str, references: list[dict], cited_ids: list[str] | None = None,
                       threshold: float = SUPPORT_THRESHOLD) -> GuardResult:
    findings: list[Finding] = []
    claim_reports = []
    ref_ids = {r["id"] for r in references}
    all_ref_numbers = set().union(*(_numbers(r["text"]) for r in references)) if references else set()
    windows = [w for r in references for w in _windows(r["text"])]

    for bad in sorted(set(cited_ids or []) - ref_ids):
        findings.append(Finding("citation_not_in_references", detail=bad))

    for claim in extract_claims(answer):
        stems = _content(claim)
        best_cov, best_win = 0.0, ""
        for w in windows:
            wset = set(_content(w))
            cov = sum(1 for s in stems if s in wset) / len(stems)
            if cov > best_cov:
                best_cov, best_win = cov, w
        reasons = []
        if best_cov < threshold:
            reasons.append(f"low_support({best_cov:.2f})")
        if not _numbers(claim) <= all_ref_numbers:
            reasons.append("number_not_in_references")
        if best_win and best_cov >= 0.5 and _negated(claim) != _negated(best_win):
            reasons.append("negation_mismatch")
        supported = not reasons
        claim_reports.append({"claim": claim, "coverage": round(best_cov, 2), "supported": supported, "reasons": reasons})
        if not supported:
            findings.append(Finding("unsupported_claim", detail=f"{claim} :: {','.join(reasons)}"))

    flagged = bool(findings)
    return GuardResult(
        guard="groundedness", flagged=flagged,
        action="regenerate" if flagged else "allow",
        findings=findings,
        details={"claims": claim_reports, "threshold": threshold},
    )
