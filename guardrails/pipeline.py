"""End-to-end guardrail pipeline.

    user text
      |-- INPUT GUARDRAILS (run on raw text, all independent)
      |      injection | topic | PII
      |-- decision: crisis / refuse / block, or continue with PII-redacted text
      |-- retrieval (on redacted text)
      |-- LLM call
      |-- OUTPUT GUARDRAILS (per attempt; up to MAX_REGENERATIONS retries)
      |      schema -> sensitive-info -> groundedness
      |-- post-processing (topic disclaimers, forced escalation)
      '-- response  (answered | crisis | refused | blocked | fallback)

Failure handling
----------------
schema invalid        -> regenerate (strict) -> fallback
ungrounded            -> regenerate (strict) -> fallback
secret / high-risk PII-> regenerate (strict) -> fallback   (never redact-and-deliver)
low-risk PII (e-mail, phone) -> redact and deliver
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .groundedness import check_groundedness
from .injection import detect_injection
from .knowledge_base import SUPPORT_EMAIL, retrieve
from .llm import MockLLM
from .output_sensitive import check_output_sensitive
from .pii import detect_pii, redact
from .schema import check_schema
from .topics import classify_topic

MAX_REGENERATIONS = 1

MESSAGES = {
    "blocked": "I can't help with that request. If you have a question about your HimalPay account, I'm happy to help.",
    "refuse": "I'm sorry, I can't help with that. I can answer questions about HimalPay accounts, transfers, fees, KYC and refunds.",
    "medical": "That's outside what I can help with. For health questions please speak to a qualified medical professional.",
    "crisis": ("I'm really sorry you're going through this. You don't have to face it alone. Please contact your local "
               "emergency services or a crisis helpline in your area, or reach out to someone you trust right now. "
               "I'm also asking a member of our support team to contact you."),
    "fallback": f"I'm sorry, I can't give a reliable answer right now. I've passed your question to a support agent; you can also email {SUPPORT_EMAIL}.",
}
DISCLAIMERS = {
    "investment": "Note: this is product information only, not financial advice.",
    "legal": "Note: this is general product information, not legal advice. A support agent will follow up.",
    "security_incident": "This looks urgent. A support agent has been alerted and will contact you.",
}


@dataclass
class PipelineResponse:
    status: str                      # answered | crisis | refused | blocked | fallback
    message: str
    answer: dict[str, Any] | None = None
    requires_human: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)


class GuardrailPipeline:
    def __init__(self, llm: MockLLM | None = None):
        self.llm = llm or MockLLM()

    # ------------------------------------------------------------------
    def handle(self, user_text: str) -> PipelineResponse:
        trace: list[dict[str, Any]] = []

        inj = detect_injection(user_text)
        topic = classify_topic(user_text)
        pii = detect_pii(user_text)
        trace += [{"stage": "input", **g.summary()} for g in (inj, topic)]
        trace.append({"stage": "input", "guard": "pii", "flagged": bool(pii),
                      "action": "redact" if pii else "allow", "kinds": sorted({f.kind for f in pii})})
        primary = topic.details.get("primary")

        # --- decisions that stop the request before the model is called -----
        if primary == "self_harm":                 # safety beats everything, even an injection flag
            return PipelineResponse("crisis", MESSAGES["crisis"], requires_human=True, trace=trace)
        if inj.flagged:
            return PipelineResponse("blocked", MESSAGES["blocked"], trace=trace)
        if primary in ("violence", "illegal_activity"):
            return PipelineResponse("refused", MESSAGES["refuse"], trace=trace)
        if primary == "medical":
            return PipelineResponse("refused", MESSAGES["medical"], trace=trace)

        # --- redact PII, retrieve, generate --------------------------------
        safe_text = redact(user_text, pii) if pii else user_text
        # security incidents: steer retrieval to the "block your wallet" article
        query = safe_text + " block wallet lost" if primary == "security_incident" else safe_text
        passages = retrieve(query)
        trace.append({"stage": "retrieval", "ids": [p["id"] for p in passages]})

        obj = None
        for attempt in range(MAX_REGENERATIONS + 1):
            raw = self.llm.generate(safe_text, passages, strict=attempt > 0)
            obj, ok = self._check_output(raw, passages, trace, attempt)
            if ok:
                break
            obj = None
        if obj is None:
            return PipelineResponse("fallback", MESSAGES["fallback"], requires_human=True, trace=trace)

        # --- post-processing -------------------------------------------------
        message = obj["answer"]
        requires_human = obj["requires_human"]
        if primary in DISCLAIMERS:
            message = f"{DISCLAIMERS[primary]} {message}" if primary == "security_incident" else f"{message} {DISCLAIMERS[primary]}"
        if primary in ("legal", "security_incident"):
            requires_human = True
        obj = dict(obj, requires_human=requires_human)
        return PipelineResponse("answered", message, answer=obj, requires_human=requires_human, trace=trace)

    # ------------------------------------------------------------------
    def _check_output(self, raw: str, passages: list[dict], trace: list, attempt: int):
        sch = check_schema(raw)
        trace.append({"stage": "output", "attempt": attempt, **sch.summary()})
        if sch.flagged:
            return None, False
        obj = dict(sch.details["object"])

        sens = check_output_sensitive(obj["answer"])
        trace.append({"stage": "output", "attempt": attempt, **sens.summary()})
        if sens.action == "block":
            return None, False
        if sens.action == "redact":
            obj["answer"] = sens.sanitized_text

        gnd = check_groundedness(obj["answer"], passages, obj["sources"])
        trace.append({"stage": "output", "attempt": attempt, **gnd.summary()})
        if gnd.flagged:
            return None, False
        return obj, True
