"""Cumulative cost ledger across all cooperbench runs in ./logs.

Sums total_cost from each run's summary.json, and independently recomputes
cost from per-call token usage in the trajectories (cross-check), broken
down by model. Run anytime: `uv run python cost_ledger.py`
"""
import json, glob, os
from collections import defaultdict

# $/token (input, output) — from litellm registry, per 1M shown for reference
PRICE = {
    "gpt-5.4":      (2.50e-6, 15.0e-6),
    "gpt-5.4-mini": (0.75e-6, 4.50e-6),
    "gpt-5-nano":   (0.05e-6, 0.40e-6),
}
def price_for(model):
    m = (model or "").split("/")[-1]
    return PRICE.get(m, (0.0, 0.0))

runs = sorted(glob.glob("logs/*/summary.json"))
grand_summary = 0.0
tok = defaultdict(lambda: [0, 0, 0.0, 0])  # model -> [in, out, recomputed_cost, llm_calls]
print(f"{'run':28s} {'cost($)':>9s} {'time(s)':>8s} {'pass':>6s}")
print("-"*56)
for s in runs:
    d = json.loads(open(s).read())
    grand_summary += d.get("total_cost") or 0
    print(f"{d['run_name']:28s} {d.get('total_cost') or 0:9.4f} {d.get('total_time_seconds') or 0:8.0f} {d.get('pass_rate',0):6.0%}")
    rundir = os.path.dirname(s)
    for tj in glob.glob(rundir + "/**/*traj*.json", recursive=True):
        dd = json.loads(open(tj).read())
        model = dd.get("model", "?")
        pin, pout = price_for(model)
        for m in dd.get("messages", []):
            resp = (m.get("extra") or {}).get("response") or {}
            u = resp.get("usage") or {}
            if u:
                i, o = u.get("prompt_tokens", 0) or 0, u.get("completion_tokens", 0) or 0
                t = tok[model]; t[0]+=i; t[1]+=o; t[2]+=i*pin+o*pout; t[3]+=1

print("-"*56)
print(f"{'TOTAL (from summary.json)':28s} {grand_summary:9.4f}")
print("\n=== per-model token usage (recomputed from trajectories) ===")
recomputed = 0.0
for model, (i, o, c, n) in sorted(tok.items()):
    recomputed += c
    print(f"  {model:16s} calls={n:4d}  in={i:>10,d}  out={o:>8,d}  cost=${c:.4f}")
print(f"  recomputed total = ${recomputed:.4f}  (cross-check vs summary ${grand_summary:.4f})")
