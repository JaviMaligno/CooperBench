"""Aggregate the headline QA-d cells across seeds -> mean +/- range.

Seed naming: seed 1 = original runs (no suffix, e.g. F-mini-solo),
seed 2/3 = -s2/-s3 suffix. For each (tier, condition) cell we report each
seed's pass count and the mean/min/max across the seeds that exist, so the
table can carry error bars instead of single-run points.

Usage: .venv/bin/python aggregate_seeds.py
"""

import glob
import json
import os

ROOT = "logs"
TIERS = ["mini", "large"]
CONDS = ["solo", "coop", "seq", "c4"]
SEEDS = ["", "-s2", "-s3"]  # "" == seed 1 (original run)


def run_dir(tier, cond, seed):
    return f"F-{tier}-{cond}{seed}"


def pass_count(run, use_resolver=False):
    """(passed, n, evaluated) for a run dir; None if the run doesn't exist."""
    base = os.path.join(ROOT, run)
    if not os.path.isdir(base):
        return None
    passed = n = evaluated = 0
    for e in glob.glob(f"{base}/*/*/*/f*/eval.json"):
        n += 1
        path = e
        if use_resolver:
            alt = e.replace("eval.json", "eval_resolver.json")
            if os.path.exists(alt):
                path = alt
        try:
            d = json.load(open(path))
        except Exception:
            continue
        evaluated += 1
        if d.get("both_passed"):
            passed += 1
    return passed, n, evaluated


def main():
    print(f"{'cell':16} {'seed1':>8} {'seed2':>8} {'seed3':>8}   mean±range (pass-rate on evaluated)")
    print("-" * 78)
    for tier in TIERS:
        for cond in CONDS:
            cells = []
            display = []
            for seed in SEEDS:
                pc = pass_count(run_dir(tier, cond, seed))
                if pc is None:
                    display.append(f"{'--':>8}")
                    continue
                passed, n, evaluated = pc
                if evaluated == 0:
                    # run exists but nothing scored yet -> not a data point
                    display.append(f"{'(0/0)':>8}")
                    continue
                rate = passed / evaluated
                partial = "" if evaluated == n else f"~{evaluated}/{n}"
                display.append(f"{passed}/{evaluated}{partial:>0}".rjust(8))
                cells.append(rate)
            if cells:
                mean = sum(cells) / len(cells)
                lo, hi = min(cells), max(cells)
                summary = f"{mean*100:.0f}% [{lo*100:.0f}–{hi*100:.0f}] (n_seeds={len(cells)})"
            else:
                summary = "no data"
            print(f"F-{tier}-{cond:11} {display[0]} {display[1]} {display[2]}   {summary}")
        print()


if __name__ == "__main__":
    main()
