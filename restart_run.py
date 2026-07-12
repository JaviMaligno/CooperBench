"""Run the restart-vs-iterate loop over a feature pool.

Resumable: re-running the same --run-name skips completed features and
completed rounds. Docker-local only; source azure_env.sh first.
"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from cooperbench.restart.loop import execute_restart_loop  # noqa: E402
from cooperbench.restart.policies import POLICIES  # noqa: E402
from cooperbench.restart.pool import build_feature_pool  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--policy", required=True, choices=POLICIES)
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--subset", default="flash_amd64")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--limit", type=int, help="first N pool features (pilot)")
    ap.add_argument("--only", help="comma list repo:task_id:feature_id")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pool = build_feature_pool(args.subset)
    if args.only:
        wanted = set(args.only.split(","))
        pool = [f for f in pool
                if f"{f['repo']}:{f['task_id']}:{f['feature_id']}" in wanted]
    if args.limit:
        pool = pool[: args.limit]

    print(f"{args.run_name}: {len(pool)} features × policy={args.policy} "
          f"× K={args.rounds} × model={args.model}")
    if args.dry_run:
        for f in pool:
            print(f"  {f['repo']}:{f['task_id']}:f{f['feature_id']}")
        return

    done = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool_ex:
        futs = {
            pool_ex.submit(
                execute_restart_loop, f["repo"], f["task_id"], f["feature_id"],
                args.policy, args.run_name, args.model,
                rounds=args.rounds, force=args.force,
            ): f
            for f in pool
        }
        for fut in as_completed(futs):
            f = futs[fut]
            done += 1
            tag = f"{f['repo']}:{f['task_id']}:f{f['feature_id']}"
            try:
                r = fut.result()
                extra = "SKIP" if r.get("skipped") else \
                    f"solved={r['solved']} rounds={r['rounds_run']} ${r['total_cost']:.2f}"
                print(f"[{done}/{len(pool)}] {tag} {extra}", flush=True)
            except Exception as e:
                print(f"[{done}/{len(pool)}] {tag} ERROR: {str(e)[:150]}", flush=True)


if __name__ == "__main__":
    main()
