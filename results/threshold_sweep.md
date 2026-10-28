# Threshold sweeps

## Prompt-injection score threshold (default 0.60; 18 cases)

| Threshold | TP | FP | FN | TN | Precision | Recall |
|---:|---:|---:|---:|---:|---:|---:|
| 0.30 | 10 | 1 | 3 | 4 | 0.91 | 0.77 |
| 0.40 | 10 | 1 | 3 | 4 | 0.91 | 0.77 |
| 0.50 | 10 | 1 | 3 | 4 | 0.91 | 0.77 |
| 0.60 | 10 | 1 | 3 | 4 | 0.91 | 0.77 |
| 0.70 | 10 | 1 | 3 | 4 | 0.91 | 0.77 |
| 0.80 | 8 | 1 | 5 | 4 | 0.89 | 0.62 |
| 0.90 | 1 | 0 | 12 | 5 | 1.00 | 0.08 |

## Groundedness support threshold (default 0.70; 15 cases)

| Threshold | TP | FP | FN | TN | Precision | Recall |
|---:|---:|---:|---:|---:|---:|---:|
| 0.30 | 7 | 1 | 2 | 5 | 0.88 | 0.78 |
| 0.50 | 7 | 1 | 2 | 5 | 0.88 | 0.78 |
| 0.60 | 7 | 1 | 2 | 5 | 0.88 | 0.78 |
| 0.70 | 7 | 1 | 2 | 5 | 0.88 | 0.78 |
| 0.80 | 8 | 1 | 1 | 5 | 0.89 | 0.89 |
| 0.90 | 8 | 1 | 1 | 5 | 0.89 | 0.89 |
| 1.00 | 8 | 1 | 1 | 5 | 0.89 | 0.89 |

Positive = flagged. FP = a legitimate request / answer was blocked; FN = an attack / unsupported claim got through.
