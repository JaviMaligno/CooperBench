"""Restart-vs-iterate mining: when do agents THROW AWAY work and start over
instead of patching forward? And after an IMPOSED restart (territory revert),
do they adapt or keep flailing?

Signals of voluntary "start over" (discard own work):
  git checkout -- . / git checkout <path> / git reset --hard / git clean / git stash
Read-only over logs/. Usage: .venv/bin/python restart_mining.py
"""

import glob
import json
import re
from collections import defaultdict

DISCARD = re.compile(
    r"git\s+checkout\s+(--\s+)?\.|git\s+checkout\s+HEAD|git\s+reset\s+--hard|git\s+clean\s+-|git\s+stash(?!\s+pop)",
)


def commands(traj):
    out = []
    for m in traj.get("messages", []):
        if m.get("role") != "assistant":
            continue
        for a in (m.get("extra") or {}).get("actions", []) or []:
            c = a.get("command")
            if c:
                out.append(c)
    return out


def tier_of(run):
    if "mini" in run:
        return "mini"
    if "large" in run:
        return "large"
    return "?"


# 1) voluntary discard rate by tier (short-horizon "start over")
by_tier = defaultdict(lambda: {"trajs": 0, "discards": 0, "trajs_with_discard": 0, "cmds": 0})
# 2) adapt-after-imposed-restart: after a [Territory Enforcement] revert, does the
#    agent change files/approach (adapt) or repeat the same edit (flail)?
adapt = defaultdict(lambda: {"reverts": 0, "adapted": 0})

for t in glob.glob("logs/F-*/**/*traj*.json", recursive=True):
    run = t.split("/")[1]
    tier = tier_of(run)
    if tier == "?":
        continue
    try:
        d = json.load(open(t))
    except Exception:
        continue
    cmds = commands(d)
    disc = sum(1 for c in cmds if DISCARD.search(c))
    s = by_tier[tier]
    s["trajs"] += 1
    s["cmds"] += len(cmds)
    s["discards"] += disc
    if disc:
        s["trajs_with_discard"] += 1

    # adapt-after-revert: scan messages for enforcement notices, then whether the
    # NEXT assistant command touches a different file than the reverted one.
    msgs = d.get("messages", [])
    for i, m in enumerate(msgs):
        c = m.get("content") or ""
        if isinstance(c, list):
            c = " ".join(str(x) for x in c)
        if m.get("role") == "user" and "Territory Enforcement" in c:
            adapt[tier]["reverts"] += 1
            reverted = set(re.findall(r"([\w/]+\.\w+)", c))
            for m2 in msgs[i + 1:]:
                if m2.get("role") == "assistant":
                    nxt = " ".join(a.get("command", "") for a in (m2.get("extra") or {}).get("actions", []) or [])
                    if nxt.strip():
                        touched = set(re.findall(r"([\w/]+\.\w+)", nxt))
                        # adapted if it does NOT immediately re-touch a reverted file
                        if reverted and not (touched & reverted):
                            adapt[tier]["adapted"] += 1
                        break

print("=" * 64)
print("VOLUNTARY 'START OVER' (discard own work) by tier")
print("=" * 64)
for tier in ("mini", "large"):
    s = by_tier[tier]
    if not s["trajs"]:
        continue
    print(f"  {tier:5}: {s['discards']} discard-cmds across {s['trajs']} trajectories "
          f"({s['trajs_with_discard']} had >=1); {s['discards']/s['trajs']:.2f} per traj, "
          f"{s['discards']/max(s['cmds'],1)*100:.1f}% of all commands")

print()
print("=" * 64)
print("ADAPT AFTER IMPOSED RESTART (territory revert)")
print("=" * 64)
for tier in ("mini", "large"):
    a = adapt[tier]
    if not a["reverts"]:
        continue
    print(f"  {tier:5}: {a['adapted']}/{a['reverts']} reverts followed by a DIFFERENT file "
          f"({a['adapted']/a['reverts']*100:.0f}% adapt, rest re-tried the reverted file)")
