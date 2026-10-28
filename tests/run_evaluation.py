#!/usr/bin/env python3
"""Run every test case and write results + metrics.

    python -m tests.run_evaluation            # from the project root
    python -m tests.run_evaluation --strict   # exit 1 if any case fails

Outputs (results/):  test_results.json, test_results.md, metrics.md, metrics.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guardrails import (GuardrailPipeline, MockLLM, check_groundedness, check_output_sensitive,  # noqa: E402
                        check_schema, classify_topic, detect_injection, detect_pii)
from guardrails.knowledge_base import KB_BY_ID  # noqa: E402
from tests.test_cases import E2E_CASES, UNIT_CASES  # noqa: E402

RESULTS = ROOT / "results"
GUARDS = ["pii", "injection", "topic", "schema", "groundedness", "output_sensitive"]


# --------------------------------------------------------------- unit cases
def run_unit(case: dict) -> dict:
    g, text, exp = case["guardrail"], case["input"], case["expected"]
    actual: dict = {}
    if g == "pii":
        kinds = sorted({f.kind for f in detect_pii(text)})
        actual = dict(flagged=bool(kinds), types=kinds)
    elif g == "injection":
        r = detect_injection(text)
        actual = dict(flagged=r.flagged, score=round(r.score, 2), rules=r.kinds())
    elif g == "topic":
        r = classify_topic(text)
        actual = dict(flagged=r.flagged, category=r.details.get("primary"))
    elif g == "schema":
        r = check_schema(text)
        actual = dict(flagged=r.flagged, errors=r.details["errors"])
    elif g == "groundedness":
        refs = [KB_BY_ID[i] for i in case.get("refs", [])]
        cited = case.get("cited", case.get("refs", []))
        r = check_groundedness(text, refs, cited)
        actual = dict(flagged=r.flagged, reasons=[f.detail.split("::")[-1].strip() or f.kind for f in r.findings])
    elif g == "output_sensitive":
        r = check_output_sensitive(text)
        actual = dict(flagged=r.flagged, action=r.action, kinds=r.kinds())

    ok = actual["flagged"] == exp["flagged"]
    if ok and exp["flagged"]:
        if "types" in exp:
            ok = sorted(exp["types"]) == actual["types"]
        if "category" in exp:
            ok = exp["category"] == actual["category"]
        if "action" in exp:
            ok = exp["action"] == actual["action"]
    outcome = {(True, True): "TP", (True, False): "FP", (False, True): "FN", (False, False): "TN"}[
        (actual["flagged"], exp["flagged"])]
    return dict(id=case["id"], guardrail=g, kind=case["kind"], input=text, refs=case.get("refs"),
                expected=exp, actual=actual, passed=ok, outcome=outcome)


# ------------------------------------------------------------ end-to-end
def _checks(name: str, resp, llm: MockLLM, text: str) -> bool:
    if name == "none":
        return True
    if name == "answer_mentions_100000":
        return "100,000" in resp.message
    if name == "llm_not_called":
        return not llm.calls
    if name == "llm_never_saw_raw_pii":
        return bool(llm.calls) and all("ram.sharma@gmail.com" not in c["user"] and "[EMAIL]" in c["user"] for c in llm.calls)
    if name == "regenerated_once":
        return len(llm.calls) == 2 and llm.calls[1]["strict"]
    if name == "answer_has_no_email":
        return not re.search(r"@gmail\.com", resp.message)
    if name == "has_disclaimer":
        return "not financial advice" in resp.message
    if name == "requires_human":
        return resp.requires_human
    raise ValueError(name)


def run_e2e(case: dict) -> dict:
    llm = MockLLM(list(case["fault_plan"]))
    resp = GuardrailPipeline(llm).handle(case["input"])
    status_ok = resp.status == case["expected_status"]
    check_ok = _checks(case["check"], resp, llm, case["input"])
    return dict(id=case["id"], guardrail="end_to_end", kind="pipeline", input=case["input"],
                expected=dict(status=case["expected_status"], check=case["check"]),
                actual=dict(status=resp.status, check_ok=check_ok, llm_calls=len(llm.calls),
                            message=resp.message[:120]),
                passed=status_ok and check_ok, outcome="")


# ---------------------------------------------------------------- metrics
def metrics(rows: list[dict]) -> dict:
    tp = sum(r["outcome"] == "TP" for r in rows)
    fp = sum(r["outcome"] == "FP" for r in rows)
    fn = sum(r["outcome"] == "FN" for r in rows)
    tn = sum(r["outcome"] == "TN" for r in rows)
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    return dict(n=len(rows), tp=tp, fp=fp, fn=fn, tn=tn, precision=prec, recall=rec, f1=f1,
                accuracy=(tp + tn) / len(rows) if rows else None,
                passed=sum(r["passed"] for r in rows),
                label_mismatch=sum(1 for r in rows if r["outcome"] in ("TP", "TN") and not r["passed"]))


def pct(x) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def short(s, n=70) -> str:
    s = str(s).replace("\n", " ").replace("|", "\\|")
    return s if len(s) <= n else s[: n - 1] + "…"


def fmt(d) -> str:
    return short(json.dumps(d, ensure_ascii=False), 90)


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    rows = [run_unit(c) for c in UNIT_CASES]
    e2e = [run_e2e(c) for c in E2E_CASES]
    allrows = rows + e2e
    by_guard = {g: [r for r in rows if r["guardrail"] == g] for g in GUARDS}
    m = {g: metrics(rs) for g, rs in by_guard.items()}
    m["ALL_UNIT"] = metrics(rows)

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "test_results.json").write_text(json.dumps(allrows, indent=2, ensure_ascii=False))
    (RESULTS / "metrics.json").write_text(json.dumps(m, indent=2))

    # ---- metrics.md
    out = ["# Evaluation metrics", "",
           "Positive class = \"content should be flagged\". Precision = TP/(TP+FP), recall = TP/(TP+FN).",
           "`Pass` counts cases whose detection AND detail (type / category / action) matched the expectation.", "",
           "| Guardrail | Cases | Pass | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for g in GUARDS + ["ALL_UNIT"]:
        x = m[g]
        out.append(f"| {g} | {x['n']} | {x['passed']} | {x['tp']} | {x['fp']} | {x['fn']} | {x['tn']} | "
                   f"{pct(x['precision'])} | {pct(x['recall'])} | {pct(x['f1'])} | {pct(x['accuracy'])} |")
    e2e_pass = sum(r["passed"] for r in e2e)
    out += ["", f"End-to-end pipeline cases: **{e2e_pass}/{len(e2e)}** passed.", "",
            "## Failed cases", "", "| ID | Guardrail | Outcome | Input | Expected | Actual |", "|---|---|---|---|---|---|"]
    for r in allrows:
        if not r["passed"]:
            out.append(f"| {r['id']} | {r['guardrail']} | {r['outcome'] or '-'} | {short(r['input'], 60)} | "
                       f"{fmt(r['expected'])} | {fmt(r['actual'])} |")
    labelled = [r for r in rows if r["outcome"] in ("TP", "TN") and not r["passed"]]
    if labelled:
        out += ["", "_Note: some rows above were detected correctly but with the wrong type / category / action._"]
    (RESULTS / "metrics.md").write_text("\n".join(out) + "\n")

    # ---- test_results.md (every case)
    res = ["# Test results (all cases)", "",
           "| ID | Guardrail | Kind | Input | Reference | Expected | Actual | Result |", "|---|---|---|---|---|---|---|---|"]
    for r in allrows:
        res.append(f"| {r['id']} | {r['guardrail']} | {r['kind']} | {short(r['input'], 60)} | "
                   f"{', '.join(r['refs']) if r.get('refs') else ''} | {fmt(r['expected'])} | {fmt(r['actual'])} | "
                   f"{'PASS' if r['passed'] else '**FAIL**'} |")
    (RESULTS / "test_results.md").write_text("\n".join(res) + "\n")

    # ---- console summary
    print(f"{'guardrail':18} {'n':>3} {'pass':>4} {'TP':>3} {'FP':>3} {'FN':>3} {'TN':>3}  prec  rec   f1")
    for g in GUARDS + ["ALL_UNIT"]:
        x = m[g]
        print(f"{g:18} {x['n']:>3} {x['passed']:>4} {x['tp']:>3} {x['fp']:>3} {x['fn']:>3} {x['tn']:>3}  "
              f"{pct(x['precision'])}  {pct(x['recall'])}  {pct(x['f1'])}")
    print(f"end-to-end: {e2e_pass}/{len(e2e)} passed")
    failed = [r for r in allrows if not r["passed"]]
    print(f"\n{len(failed)} failing case(s):")
    for r in failed:
        print(f"  {r['id']:7} {r['outcome'] or '-':2}  exp={fmt(r['expected'])}  act={fmt(r['actual'])}")
    return 1 if (args.strict and failed) else 0


if __name__ == "__main__":
    sys.exit(main())
