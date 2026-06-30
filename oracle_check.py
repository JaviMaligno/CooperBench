"""Oracle validation: apply each feature's GOLD patch and run its tests.
Every (task, feature) in the `core` subset must pass — confirms the eval
harness + task images are correct before we trust agent results.
Parallelized + unbuffered so progress is visible.
"""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from cooperbench.eval.sandbox import run_patch_test

core = json.loads(Path("dataset/subsets/core.json").read_text())
jobs = []
for t in core["tasks"]:
    feats = sorted({f for pair in t["pairs"] for f in pair})
    for fid in feats:
        jobs.append((t["repo"], t["task_id"], fid))

def run(job):
    repo, tid, fid = job
    return job, run_patch_test(repo, tid, fid, agent_patch=None, backend="docker")

print(f"oracle: {len(jobs)} (task,feature) checks, 5 workers", flush=True)
rows = []
with ThreadPoolExecutor(max_workers=5) as ex:
    futs = {ex.submit(run, j): j for j in jobs}
    for f in as_completed(futs):
        job, r = f.result()
        ok = r.get("passed")
        rows.append((job, ok, r))
        print(f"{'PASS' if ok else 'FAIL'}  {job[0]}/task{job[1]} f{job[2]}  "
              f"+{r.get('tests_passed')}/-{r.get('tests_failed')}  {r.get('error') or ''}", flush=True)

n = len(rows); npass = sum(1 for x in rows if x[1])
print(f"\nORACLE: {npass}/{n} passed ({100*npass/n:.0f}%)", flush=True)
for job, ok, r in rows:
    if not ok:
        print("  FAIL", job, "err=", r.get("error"), "out_tail=", (r.get("output") or "")[-200:], flush=True)
