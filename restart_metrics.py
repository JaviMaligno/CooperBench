"""Aggregate restart-loop artifacts: pass rates, curves, plateaus, McNemar.

Reads only persisted result.json files — re-analyzable without re-spending.
--gate applies the pilot thresholds from experiment/RESTART_DESIGN.md.
"""

import argparse
import glob
import json
import math


def curve(rounds: list[dict]) -> list[int]:
    return [r.get("tests_passed") or 0 for r in rounds]


def is_plateau(c: list[int], window: int = 2, solved: bool = False) -> bool:
    if solved or len(c) < window + 1:
        return False
    tail = c[-(window + 1):]
    return max(tail[1:]) <= tail[0]


def mcnemar(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, sum(math.comb(n, i) for i in range(k + 1)) * 0.5 ** n * 2)


def load_run(run_name: str) -> dict:
    """feature-key -> result.json dict."""
    out = {}
    for p in glob.glob(f"logs/{run_name}/restart/*/*/f*/result.json"):
        with open(p) as f:
            d = json.load(f)
        out[f"{d['repo']}:{d['task_id']}:{d['feature_id']}"] = d
    return out


def summarize(run_name: str, results: dict) -> None:
    n = len(results)
    solved = [r for r in results.values() if r["solved"]]
    plateaus = sum(
        1 for r in results.values()
        if is_plateau(curve(r["rounds"]), solved=r["solved"])
    )
    first_round = sum(1 for r in results.values() if r.get("solve_round") == 1)
    mean_rounds = (sum(r["solve_round"] for r in solved) / len(solved)) if solved else 0
    mean_cost = (sum(r["total_cost"] for r in solved) / len(solved)) if solved else 0
    print(f"{run_name}: solved {len(solved)}/{n} "
          f"(first-round {first_round}/{n}) | plateaus {plateaus}/{n} | "
          f"mean rounds-to-solve {mean_rounds:.1f} | mean $-to-solve {mean_cost:.2f}")


def paired(a: dict, b: dict) -> tuple[int, int]:
    only_a = only_b = 0
    for k in set(a) & set(b):
        if a[k]["solved"] and not b[k]["solved"]:
            only_a += 1
        elif b[k]["solved"] and not a[k]["solved"]:
            only_b += 1
    return only_a, only_b


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="comma-separated run names")
    ap.add_argument("--gate", action="store_true")
    args = ap.parse_args()

    runs = {name: load_run(name) for name in args.runs.split(",")}
    for name, res in runs.items():
        summarize(name, res)

    names = list(runs)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            b, c = paired(runs[names[i]], runs[names[j]])
            print(f"  {names[i]} vs {names[j]}: only-first={b} only-second={c} "
                  f"p={mcnemar(b, c):.3f}")

    if args.gate:
        allr = [r for res in runs.values() for r in res.values()]
        n = len(allr)
        fr = sum(1 for r in allr if r.get("solve_round") == 1) / max(n, 1)
        pl = sum(1 for r in allr if is_plateau(curve(r["rounds"]), solved=r["solved"]))
        verdict = "USEFUL ZONE" if 0.2 <= fr <= 0.6 and pl >= 1 else (
            "TOO EASY (escalate)" if fr > 0.6 else "TOO HARD/NO SIGNAL (escalate)")
        print(f"GATE: first-round solve {fr:.0%}, plateaus {pl}/{n} -> {verdict}")


if __name__ == "__main__":
    main()
