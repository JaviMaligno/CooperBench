"""Deep analysis of a combo run vs its component conditions.

Two lenses:
 1. Paired task-level comparison of the combo vs each component (reference
    runs), with exact McNemar — does the combo beat its parts?
 2. Reviewer/integrator activity: how often the extra stage actually edits
    (empty patch => the combo is its component by construction), and its
    size. A combo that "does nothing" and one that "edits but doesn't help"
    are different findings.

Read-only over logs/ (no docker, no Azure). Usage:
    .venv/bin/python combo_analysis.py <combo_setting> <extra_patch_name>
e.g. combo_analysis.py c3c4 reviewer.patch
     combo_analysis.py c2c4 integrator.patch
"""

import glob
import json
import math
import os
import sys

COMBO = sys.argv[1] if len(sys.argv) > 1 else "c3c4"
EXTRA = sys.argv[2] if len(sys.argv) > 2 else "reviewer.patch"
# which component conditions to compare against (reference single-seed runs)
COMPONENTS = {"c3c4": ["seq", "c4"], "c2c4": ["c4", "C2"], "c1c2": ["C1", "C2"]}[COMBO]


def mcnemar(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, sum(math.comb(n, i) for i in range(k + 1)) * 0.5 ** n * 2)


def load(run, setting_dir):
    out = {}
    for e in glob.glob(f"logs/{run}/{setting_dir}/*/*/f*/eval.json"):
        d = json.load(open(e))
        out["/".join(e.split("/")[-4:-1])] = bool(d.get("both_passed"))
    return out


def paired(a, b):
    B = C = 0
    for k, va in a.items():
        suf = k.split("/", 1)[1]
        for k2, vb in b.items():
            if k2.endswith(suf):
                if va and not vb:
                    B += 1
                elif vb and not va:
                    C += 1
                break
    return B, C


# c1c2 is coop-with-flags, so its logs live under the coop/ subdir.
COMBO_DIR = "coop" if COMBO == "c1c2" else COMBO

for tier in ("mini", "large"):
    combo = load(f"F-{tier}-{COMBO}", COMBO_DIR)
    if not combo:
        print(f"[{tier}] no {COMBO} data yet")
        continue
    passes = sum(combo.values())
    print(f"\n=== {tier}: {COMBO} = {passes}/{len(combo)} ===")
    for comp in COMPONENTS:
        # component reference run dir + its on-disk setting subdir
        comp_dir = "coop" if comp in ("C1", "C2", "C2b") else comp
        comp_run = f"F-{tier}-{comp}"
        ref = load(comp_run, comp_dir)
        if not ref:
            print(f"  vs {comp}: (no reference run)")
            continue
        B, C = paired(combo, ref)  # B = only combo, C = only component
        print(f"  vs {comp:4} ({sum(ref.values())}/{len(ref)}):  only-{COMBO}={B}  only-{comp}={C}  McNemar p={mcnemar(B, C):.3f}")

    # extra-stage activity
    empty = nonempty = 0
    sizes = []
    for rp in glob.glob(f"logs/F-{tier}-{COMBO}/{COMBO_DIR}/*/*/f*/{EXTRA}"):
        n = len([ln for ln in open(rp, errors="ignore").read().splitlines() if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))])
        if n == 0:
            empty += 1
        else:
            nonempty += 1
            sizes.append(n)
    med = sorted(sizes)[len(sizes) // 2] if sizes else 0
    print(f"  {EXTRA}: empty={empty} nonempty={nonempty} (median +/- lines when acting: {med})")
