#!/usr/bin/env python3
"""Sweep the two tunable thresholds to show the safety / usability trade-off.

    python -m tests.threshold_sweep       ->  results/threshold_sweep.md
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guardrails import check_groundedness, detect_injection  # noqa: E402
from guardrails.knowledge_base import KB_BY_ID  # noqa: E402
from tests.test_cases import GROUND, INJ  # noqa: E402


def confusion(pred_exp):
    tp = sum(p and e for p, e in pred_exp)
    fp = sum(p and not e for p, e in pred_exp)
    fn = sum((not p) and e for p, e in pred_exp)
    tn = sum((not p) and (not e) for p, e in pred_exp)
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    return tp, fp, fn, tn, prec, rec


def row(label, c):
    tp, fp, fn, tn, p, r = c
    return f"| {label} | {tp} | {fp} | {fn} | {tn} | {p:.2f} | {r:.2f} |"


def main() -> None:
    hdr = ["| Threshold | TP | FP | FN | TN | Precision | Recall |", "|---:|---:|---:|---:|---:|---:|---:|"]
    out = ["# Threshold sweeps", "",
           f"## Prompt-injection score threshold (default 0.60; {len(INJ)} cases)", ""] + hdr
    for t in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        pe = [(detect_injection(c["input"], threshold=t).flagged, c["expected"]["flagged"]) for c in INJ]
        out.append(row(f"{t:.2f}", confusion(pe)))

    out += ["", f"## Groundedness support threshold (default 0.70; {len(GROUND)} cases)", ""] + hdr
    for t in (0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        pe = []
        for c in GROUND:
            refs = [KB_BY_ID[i] for i in c.get("refs", [])]
            r = check_groundedness(c["input"], refs, c.get("cited", c.get("refs", [])), threshold=t)
            pe.append((r.flagged, c["expected"]["flagged"]))
        out.append(row(f"{t:.2f}", confusion(pe)))
    out += ["", "Positive = flagged. FP = a legitimate request / answer was blocked; FN = an attack / unsupported claim got through."]
    (ROOT / "results" / "threshold_sweep.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
