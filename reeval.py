"""Targeted re-evaluation of specific pair dirs (QA phase).

Two modes:
  --mode resolver : re-run test_merged with COOPERBENCH_LLM_RESOLVER=1 on
                    coop-family pairs; writes eval_resolver.json alongside
                    the original eval.json (baseline is preserved).
  --mode official : re-run the standard eval (after harness fixes, e.g. the
                    Go test-file filter); backs up eval.json to
                    eval_pre_qa.json and overwrites eval.json.

Pair dirs are given as logs/<run>/<setting>/<repo>/<task>/<fA_fB> paths,
one per line on stdin or as CLI args. Requires Azure env (source
azure_env.sh) in resolver mode. Docker backend only.
"""

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from cooperbench.eval.sandbox import test_merged, test_sequential, test_solo  # noqa: E402


def pair_info(pair_dir: Path) -> dict:
    parts = pair_dir.parts
    # .../logs/<run>/<setting>/<repo>/<task>/<fA_fB>
    fa, fb = (int(x[1:]) for x in parts[-1].split("_"))
    return {
        "run": parts[-5],
        "setting": parts[-4],
        "repo": parts[-3],
        "task_id": int(parts[-2]),
        "f1": fa,
        "f2": fb,
    }


def eval_pair(pair_dir: Path, mode: str) -> dict:
    info = pair_info(pair_dir)
    repo, task_id, f1, f2 = info["repo"], info["task_id"], info["f1"], info["f2"]
    setting = info["setting"]

    if setting == "solo":
        result = test_solo(repo, task_id, f1, f2, patch=pair_dir / "solo.patch")
    elif setting == "c3c4":
        # sequential pipeline (A, then B on A) + reviewer over the A+B tree
        result = test_sequential(
            repo, task_id, f1, f2,
            patch_a=pair_dir / f"agent{f1}.patch",
            patch_b=pair_dir / f"agent{f2}.patch",
            patch_c=pair_dir / "reviewer.patch",
        )
    elif setting in ("seq", "c2c4"):
        # seq dirs hold agent{f1}.patch (A) and agent{f2}.patch (B, stacked);
        # c4/c2c4 dirs additionally hold integrator.patch which replaces B's patch.
        patch_b = pair_dir / "integrator.patch"
        if not patch_b.exists():
            patch_b = pair_dir / f"agent{f2}.patch"
        result = test_sequential(
            repo, task_id, f1, f2,
            patch_a=pair_dir / f"agent{f1}.patch",
            patch_b=patch_b,
        )
    else:  # coop family (coop/team/C1/C2/C2b live under setting dir "coop")
        result = test_merged(
            repo, task_id, f1, f2,
            patch1=pair_dir / f"agent{f1}.patch",
            patch2=pair_dir / f"agent{f2}.patch",
        )

    out_name = "eval_resolver.json" if mode == "resolver" else "eval.json"
    if mode == "official":
        orig = pair_dir / "eval.json"
        backup = pair_dir / "eval_pre_qa.json"
        if orig.exists() and not backup.exists():
            backup.write_text(orig.read_text())
    (pair_dir / out_name).write_text(json.dumps(result, indent=2))
    return {"pair": str(pair_dir), "both_passed": result.get("both_passed"), "merge": (result.get("merge") or {}).get("strategy")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["resolver", "official"], required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("pairs", nargs="*")
    args = ap.parse_args()

    if args.mode == "resolver":
        os.environ["COOPERBENCH_LLM_RESOLVER"] = "1"

    pairs = [Path(p) for p in (args.pairs or [ln.strip() for ln in sys.stdin if ln.strip()])]
    for p in pairs:
        assert p.is_dir(), f"not a dir: {p}"

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(eval_pair, p, args.mode): p for p in pairs}
        for fut in as_completed(futs):
            done += 1
            try:
                r = fut.result()
                print(f"[{done}/{len(pairs)}] {r['pair']}  both_passed={r['both_passed']}  strategy={r['merge']}", flush=True)
            except Exception as e:
                print(f"[{done}/{len(pairs)}] {futs[fut]}  ERROR: {re.sub(chr(10), ' ', str(e))[:200]}", flush=True)


if __name__ == "__main__":
    main()
