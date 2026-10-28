"""Sensitive-topic classification (keyword / pattern based) with per-category actions.

Priority order (highest first) decides the primary category when several match:
self_harm > violence > illegal_activity > security_incident > legal > medical > investment

Actions
-------
self_harm         -> crisis        : no LLM call; supportive message + advise contacting emergency
                                     services / trusted person; escalate to a human agent.
violence          -> refuse        : fixed refusal, no LLM call.
illegal_activity  -> refuse        : fixed refusal, no LLM call.
security_incident -> escalate      : answer from KB, force requires_human=True, prepend urgent notice.
legal             -> disclaimer    : answer product facts only, add "not legal advice", requires_human.
medical           -> refuse        : out-of-scope message, no LLM call.
investment        -> disclaimer    : answer product facts only, add "not financial advice".

Known limitations (see REPORT.md): keyword matching misses euphemisms and
non-English text, and over-triggers on keywords used innocently
(e.g. "my lawyer needs my statements").
"""
from __future__ import annotations

import re

from .types import Finding, GuardResult

I = re.I
CATEGORIES: list[tuple[str, re.Pattern, str]] = [
    ("self_harm", re.compile(
        r"\b(?:kill(?:ing)?\s+myself|end(?:ing)?\s+(?:my\s+life|it\s+all)|suicid(?:e|al)|want\s+to\s+die"
        r"|don'?t\s+want\s+to\s+(?:live|be\s+alive)|hurt(?:ing)?\s+myself|self[\s-]?harm"
        r"|better\s+off\s+(?:dead|without\s+me)|no\s+reason\s+to\s+live|cut(?:ting)?\s+myself)\b", I), "crisis"),
    ("violence", re.compile(
        r"\b(?:make|build|create|assemble|construct)\s+(?:a\s+|an\s+)?(?:bomb|explosive|weapon|gun|grenade)\b"
        r"|\bhow\s+to\s+(?:kill|murder|poison)\b|\bbomb\s+threat\b", I), "refuse"),
    ("illegal_activity", re.compile(
        r"\b(?:launder(?:ing)?|money\s+laundering"
        r"|hack(?:ing)?\s+(?:into\s+)?(?:someone|another|other|a|an|their|his|her)\b"
        r"|steal(?:ing)?\s+(?:money|funds|cards?|accounts?|identity|otps?)"
        r"|(?:fake|forged?|counterfeit)\s+(?:citizenship|passport|id|documents?|kyc|cards?|identity)"
        r"|bypass(?:ing)?\s+(?:kyc|verification|aml)|evade\s+(?:tax|aml|kyc)"
        r"|phishing\s+(?:page|site|kit)|clone\s+(?:a\s+)?(?:card|sim)|sim\s+swap)", I), "refuse"),
    ("security_incident", re.compile(
        r"\b(?:unauthori[sz]ed|fraudulent|suspicious|unknown)\s+(?:transactions?|transfers?|logins?|activity|payments?|access)"
        r"|\b(?:account|wallet)\b[^.?!]{0,30}\b(?:hacked|compromised|stolen|taken\s+over)"
        r"|\b(?:hacked|compromised)\b|\blost\s+(?:my\s+)?(?:phone|card|sim|device)"
        r"|\bstolen\s+(?:phone|card|sim)\b|\bscam(?:med)?\b|\bgave\s+(?:out\s+)?(?:my\s+)?(?:otp|pin|password)", I), "escalate"),
    ("legal", re.compile(
        r"\b(?:sue|suing|lawsuit|legal\s+action|court|attorney|lawyer|legal\s+advice|file\s+a\s+case|police\s+complaint)\b", I),
     "disclaimer"),
    ("medical", re.compile(
        r"\b(?:medication|medicine|prescription|diagnos(?:e|is)|symptoms?|headache|fever|dosage|treatment\s+for|disease|pain\s+in)\b", I),
     "refuse"),
    ("investment", re.compile(
        r"\b(?:should\s+i\s+(?:invest|buy|sell|trade)|invest(?:ing|ment)?\s+(?:in|advice)"
        r"|(?:which|what)\s+(?:stocks?|shares?|crypto(?:currency)?|coins?)|bitcoin|crypto(?:currency)?"
        r"|stock\s+market|guaranteed\s+returns?|mutual\s+funds?|forex|trading\s+tips?)\b", I), "disclaimer"),
]
ACTION = {name: action for name, _, action in CATEGORIES}


def classify_topic(text: str) -> GuardResult:
    found: list[Finding] = []
    for name, pat, _ in CATEGORIES:
        m = pat.search(text)
        if m:
            found.append(Finding(name, m.start(), m.end()))
    if not found:
        return GuardResult("topic", False, "allow", [], details={"primary": None})
    primary = found[0].kind          # CATEGORIES is ordered by priority
    return GuardResult(
        "topic", True, ACTION[primary], found,
        details={"primary": primary, "all": [f.kind for f in found]},
    )
