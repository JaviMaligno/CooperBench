"""Paired McNemar tests across seeds for the headline QA-d cells.

Pairing is per-task within each seed (solo-s1 vs seq-s1, solo-s2 vs seq-s2,
...), and discordant counts are pooled across the seeds/tiers requested.
This respects the pairing (same task pair, same seed) while using all
replicate information. Exact two-sided binomial McNemar p-value.
"""

import glob
import json
import math
import os

SEEDS = ["", "-s2", "-s3"]


def mcnemar(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, sum(math.comb(n, i) for i in range(k + 1)) * 0.5 ** n * 2)


def load(run):
    """task-suffix -> both_passed for a run dir; {} if absent."""
    out = {}
    base = os.path.join("logs", run)
    if not os.path.isdir(base):
        return out
    for e in glob.glob(f"{base}/*/*/*/f*/eval.json"):
        d = json.load(open(e))
        key = "/".join(e.split("/")[-4:-1])  # repo/task/features
        out[key] = bool(d.get("both_passed"))
    return out


def paired_pooled(tiers, cond_a, cond_b):
    """Sum discordant (only-a, only-b) over seeds x tiers, pairing per task+seed."""
    B = C = npairs = 0
    for tier in tiers:
        for seed in SEEDS:
            a = load(f"F-{tier}-{cond_a}{seed}")
            b = load(f"F-{tier}-{cond_b}{seed}")
            common = set(a) & set(b)
            npairs += len(common)
            for k in common:
                if a[k] and not b[k]:
                    B += 1
                elif b[k] and not a[k]:
                    C += 1
    return npairs, B, C, mcnemar(B, C)


def report(title, tiers, comparisons):
    print(f"\n=== {title} ===")
    for a, bcond in comparisons:
        n, B, C, p = paired_pooled(tiers, a, bcond)
        star = " *" if p < 0.05 else ""
        print(f"  {a:5} vs {bcond:5}  n={n:3d}  only-{a}={B:2d}  only-{bcond}={C:2d}  p={p:.4f}{star}")


COMPARISONS = [
    ("solo", "coop"),   # the gap
    ("seq", "coop"),    # sequencing recovers?
    ("c4", "coop"),     # integrator recovers?
    ("seq", "solo"),    # does sequencing BEAT solo?
    ("c4", "solo"),     # does integrator BEAT solo?
]

report("POOLED across both tiers x 3 seeds", ["mini", "large"], COMPARISONS)
report("mini only x 3 seeds", ["mini"], COMPARISONS)
report("large only x 3 seeds", ["large"], COMPARISONS)
