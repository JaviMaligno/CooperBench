"""Isolate the effect of a combo's extra stage on the SAME A/B patches.

For each combo pair, evaluate the tree WITHOUT the extra stage and compare
to the recorded eval (WITH it). Same patch_a/patch_b, so the delta is purely
the reviewer (c3c4) / integrator (c2c4) — no cross-run nondeterminism.

  c3c4: without = test_sequential(patch_a, patch_b)          [seq-internal]
  c2c4: without = test_merged(patch_a, patch_b)              [coop-territory merge]

Writes eval_noextra.json alongside; prints rescued / broke / unchanged.
Read+docker only, no Azure. Usage: .venv/bin/python isolate_extra.py <c3c4|c2c4>
"""

import glob
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from cooperbench.eval.sandbox import test_merged, test_sequential  # noqa: E402

COMBO = sys.argv[1] if len(sys.argv) > 1 else "c3c4"


def eval_without(pair_dir: Path, f1: int, f2: int, repo: str, task_id: int) -> bool:
    a = pair_dir / f"agent{f1}.patch"
    b = pair_dir / f"agent{f2}.patch"
    if COMBO == "c3c4":
        r = test_sequential(repo, task_id, f1, f2, patch_a=a, patch_b=b)
    else:  # c2c4: the two territory-constrained patches merged, no integrator
        r = test_merged(repo, task_id, f1, f2, patch1=a, patch2=b)
    (pair_dir / "eval_noextra.json").write_text(json.dumps(r, indent=2))
    return bool(r.get("both_passed"))


def main() -> None:
    rescued = broke = same_pass = same_fail = 0
    jobs = []
    for tier in ("mini", "large"):
        for e in glob.glob(f"logs/F-{tier}-{COMBO}/{COMBO}/*/*/f*/eval.json"):
            pair_dir = Path(e).parent
            parts = pair_dir.parts
            repo, task_id = parts[-3], int(parts[-2])
            f1, f2 = (int(x[1:]) for x in parts[-1].split("_"))
            with_extra = bool(json.load(open(e)).get("both_passed"))
            jobs.append((pair_dir, f1, f2, repo, task_id, with_extra))

    def run(job):
        pair_dir, f1, f2, repo, task_id, with_extra = job
        without = eval_without(pair_dir, f1, f2, repo, task_id)
        return with_extra, without

    with ThreadPoolExecutor(max_workers=3) as pool:
        for fut in as_completed([pool.submit(run, j) for j in jobs]):
            with_extra, without = fut.result()
            if with_extra and not without:
                rescued += 1
            elif without and not with_extra:
                broke += 1
            elif with_extra:
                same_pass += 1
            else:
                same_fail += 1

    stage = "reviewer" if COMBO == "c3c4" else "integrator"
    print(f"\n=== {COMBO}: isolated effect of the {stage} (n={len(jobs)} pairs, both tiers) ===")
    print(f"  rescued (fail->pass): {rescued}")
    print(f"  broke   (pass->fail): {broke}")
    print(f"  net: {rescued - broke:+d}   (unchanged: {same_pass} pass, {same_fail} fail)")


if __name__ == "__main__":
    main()
