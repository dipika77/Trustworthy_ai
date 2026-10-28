"""Tiny knowledge base + retriever for the demo application.

Domain: customer-support assistant for "HimalPay", a fictional digital wallet.
All policies, limits, phone numbers and e-mail addresses below are made up
for the assignment.
"""
from __future__ import annotations

import re

SUPPORT_EMAIL = "support@himalpay.example"
SUPPORT_HOTLINE = "+977-1-5550100"
# Public company contact details: never treated as leaked PII in outputs.
PUBLIC_CONTACTS = (SUPPORT_EMAIL, SUPPORT_HOTLINE)

KB: list[dict] = [
    {"id": "KB-001", "category": "transfers", "title": "Daily transfer limits",
     "text": "Verified accounts can transfer up to NPR 100,000 per day, and unverified accounts up to NPR 10,000 per day."},
    {"id": "KB-002", "category": "security", "title": "Password reset",
     "text": "To reset your password, tap Forgot password in the app and follow the link we send you. "
             "The reset link is valid for 15 minutes. HimalPay support will never ask for your password or OTP."},
    {"id": "KB-003", "category": "security", "title": "Blocking a lost card or wallet",
     "text": f"If your card or phone is lost, block your wallet immediately from the app or call {SUPPORT_HOTLINE}. "
             f"You can also email {SUPPORT_EMAIL}. Blocking is free and takes effect within minutes."},
    {"id": "KB-004", "category": "fees", "title": "Transfer fees",
     "text": "Wallet-to-wallet transfers are free of charge. Wallet-to-bank transfers cost NPR 10 per transfer "
             "up to NPR 25,000 and NPR 25 above that."},
    {"id": "KB-005", "category": "refunds", "title": "Failed transaction refunds",
     "text": "Refunds for failed transactions are returned to your wallet within 3 to 5 business days."},
    {"id": "KB-006", "category": "kyc", "title": "KYC verification",
     "text": "To verify your account, upload a citizenship certificate or passport and a selfie. "
             "Verification review takes up to 2 business days."},
    {"id": "KB-007", "category": "account", "title": "Savings interest",
     "text": "Wallet savings balances earn 4 percent interest per year, paid monthly."},
    {"id": "KB-008", "category": "account", "title": "Closing your account",
     "text": "You can request account closure from Settings in the app. The wallet balance must be zero, "
             "and closure is processed within 7 days."},
]
KB_BY_ID = {d["id"]: d for d in KB}

_STOP = {
    "a", "an", "the", "is", "are", "was", "were", "do", "does", "did", "i", "my", "me", "you", "your", "to", "of",
    "in", "on", "for", "and", "or", "it", "can", "how", "what", "when", "where", "which", "who", "please",
    "tell", "about", "with", "be", "will", "this", "that", "there", "have", "has", "get", "if", "at", "from",
}


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _tokens(text: str) -> list[str]:
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text.lower())
    return [_stem(t) for t in re.findall(r"[a-z]+|\d+", text) if t not in _STOP]


def retrieve(query: str, k: int = 2, min_score: float = 0.2) -> list[dict]:
    """Rank KB entries by the share of query terms found in title + text."""
    q = set(_tokens(query))
    if not q:
        return []
    scored = []
    for doc in KB:
        d = set(_tokens(doc["title"] + " " + doc["text"]))
        score = len(q & d) / len(q)
        if score >= min_score:
            scored.append((score, doc))
    scored.sort(key=lambda x: -x[0])
    return [dict(doc, score=round(s, 3)) for s, doc in scored[:k]]
