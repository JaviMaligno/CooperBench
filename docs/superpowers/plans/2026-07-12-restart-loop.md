# Restart-vs-Iterate Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A loop-with-evaluator harness on top of CooperBench that runs one agent per feature for up to K rounds with visible test feedback, under four policies (iterate / restart-fresh / restart-informed / agent-decides), persisting per-round artifacts for offline analysis.

**Architecture:** Three isolated units — pure policy/feedback/pool/patch-scope logic (`src/cooperbench/restart/`), an orchestrating loop with injectable spawn/eval functions (`loop.py`), and repo-root entry/analysis scripts (`restart_run.py`, `restart_metrics.py`). The loop evaluates each round itself via `run_patch_test`, so there is **no eval-routing step at all** (the bug class that bit article 1 three times is designed out; the audit then focuses on round-state composition).

**Tech Stack:** Python 3.12 (`.venv/bin/python`), pytest, existing CooperBench internals (`_spawn_agent`, `run_patch_test`, `load_subset`), docker backend, Azure via `azure_env.sh`, litellm for the Phase-2 decision call.

## Global Constraints

- Branch: `experiment/restart-loop` in `/Users/javieraguilarmartin1/Documents/repos/CooperBench`. Spec: `experiment/RESTART_DESIGN.md`.
- Run everything with the repo venv: `.venv/bin/python`, `.venv/bin/pytest` (system `python3` lacks `modal` and will fail on imports).
- Azure creds: `source azure_env.sh` before any run that calls models. Docker backend only. **No redis needed** (single agent, `messaging_enabled=False`).
- K default = 4 rounds; per-process cost guard `MSWEA_GLOBAL_COST_LIMIT=25`.
- Concurrency ≤ 2 (pallets_click task2068 saturates docker-run above that).
- Feature pool: the 29 unique `(repo, task_id, feature_id)` triples in subset `flash_amd64`.
- Artifacts layout (consumed by metrics; do not change without updating Task 8):
  `logs/<run_name>/restart/<repo>/<task_id>/f<feature_id>/round_<N>/{attempt.patch, tests.json, feedback.txt, agent.json[, decision.json]}` plus a final `result.json` per feature.
- Budget/estimates rule: before each paid batch, print time + cost estimate split Azure/Modal (Modal is always $0 here).
- Commit after every green test cycle. Standard trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Feature pool builder (pure)

**Files:**
- Create: `src/cooperbench/restart/__init__.py` (empty)
- Create: `src/cooperbench/restart/pool.py`
- Test: `tests/restart/__init__.py` (empty), `tests/restart/test_pool.py`

**Interfaces:**
- Consumes: `cooperbench.runner.tasks.load_subset(subset_name, dataset_dir) -> dict` with `tasks: set[(repo, task_id)]` and `pairs: dict[(repo, task_id) -> list[[f1, f2]]]`.
- Produces: `build_feature_pool(subset_name: str, dataset_dir=None) -> list[dict]`, each `{"repo": str, "task_id": int, "feature_id": int}`, deduped, sorted by (repo, task_id, feature_id).

- [ ] **Step 1: Write the failing test**

```python
# tests/restart/test_pool.py
import json

from cooperbench.restart.pool import build_feature_pool


def _write_subset(tmp_path, name="tiny"):
    (tmp_path / "subsets").mkdir()
    (tmp_path / "subsets" / f"{name}.json").write_text(json.dumps({
        "name": name,
        "tasks": [
            {"repo": "repo_b", "task_id": 2, "pairs": [[1, 5], [5, 7]]},
            {"repo": "repo_a", "task_id": 9, "pairs": [[2, 3]]},
        ],
    }))
    return name


class TestBuildFeaturePool:
    def test_dedupes_and_sorts(self, tmp_path):
        name = _write_subset(tmp_path)
        pool = build_feature_pool(name, dataset_dir=tmp_path)
        assert pool == [
            {"repo": "repo_a", "task_id": 9, "feature_id": 2},
            {"repo": "repo_a", "task_id": 9, "feature_id": 3},
            {"repo": "repo_b", "task_id": 2, "feature_id": 1},
            {"repo": "repo_b", "task_id": 2, "feature_id": 5},  # deduped (in 2 pairs)
            {"repo": "repo_b", "task_id": 2, "feature_id": 7},
        ]

    def test_real_flash_amd64_has_29(self):
        pool = build_feature_pool("flash_amd64")
        assert len(pool) == 29
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/restart/test_pool.py -q`
Expected: FAIL / collection error `ModuleNotFoundError: cooperbench.restart`

- [ ] **Step 3: Write minimal implementation**

```python
# src/cooperbench/restart/pool.py
"""Feature pool for the restart-vs-iterate loop.

The loop's task unit is a single feature; the pool is every distinct
(repo, task_id, feature_id) appearing in a subset's pairs, frozen and
sorted so all policies see the same features in the same order.
"""

from pathlib import Path

from cooperbench.runner.tasks import load_subset


def build_feature_pool(subset_name: str, dataset_dir: Path | str | None = None) -> list[dict]:
    subset = load_subset(subset_name, dataset_dir=dataset_dir)
    triples: set[tuple[str, int, int]] = set()
    for (repo, task_id), pairs in subset["pairs"].items():
        for pair in pairs:
            for feature_id in pair:
                triples.add((repo, task_id, feature_id))
    return [
        {"repo": repo, "task_id": task_id, "feature_id": feature_id}
        for repo, task_id, feature_id in sorted(triples)
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/restart/test_pool.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/cooperbench/restart/ tests/restart/
git commit -m "restart: feature pool builder (29 unique features in flash_amd64)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Feedback formatter (pure)

**Files:**
- Create: `src/cooperbench/restart/feedback.py`
- Test: `tests/restart/test_feedback.py`

**Interfaces:**
- Consumes: the `run_patch_test` result dict: `{"passed": bool, "tests_passed": int, "tests_failed": int, "output": str, "error": str|None}`.
- Produces: `format_feedback(test_result: dict, round_idx: int, max_output_chars: int = 2000) -> str` — identical shape for every policy (spec requirement).

- [ ] **Step 1: Write the failing test**

```python
# tests/restart/test_feedback.py
from cooperbench.restart.feedback import format_feedback


class TestFormatFeedback:
    def test_failing_result_includes_counts_and_tail(self):
        fb = format_feedback(
            {"passed": False, "tests_passed": 3, "tests_failed": 2,
             "output": "x" * 5000 + "FAILED test_foo - AssertionError", "error": None},
            round_idx=1,
        )
        assert "Round 1" in fb
        assert "3 passed, 2 failed" in fb
        assert "FAILED test_foo" in fb           # tail survives truncation
        assert len(fb) < 3000                     # truncated

    def test_truncation_keeps_the_tail_not_the_head(self):
        out = "HEAD" + "y" * 5000 + "TAIL"
        fb = format_feedback({"passed": False, "tests_passed": 0,
                              "tests_failed": 1, "output": out, "error": None}, 2)
        assert "TAIL" in fb and "HEAD" not in fb

    def test_passing_result(self):
        fb = format_feedback({"passed": True, "tests_passed": 7,
                              "tests_failed": 0, "output": "all good", "error": None}, 3)
        assert "ALL TESTS PASSED" in fb

    def test_infra_error_is_labeled(self):
        fb = format_feedback({"passed": False, "tests_passed": 0, "tests_failed": 0,
                              "output": "", "error": "sandbox timeout"}, 1)
        assert "HARNESS ERROR" in fb and "sandbox timeout" in fb
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/restart/test_feedback.py -q`
Expected: FAIL `ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/cooperbench/restart/feedback.py
"""Uniform test-feedback block shown to the agent after each round.

Every policy sees this exact format (spec: identical feedback shape), so
policy contrasts can't be confounded by presentation differences. Test
output is tail-truncated: pytest/go summaries and failures print last.
"""


def format_feedback(test_result: dict, round_idx: int, max_output_chars: int = 2000) -> str:
    if test_result.get("error"):
        return (
            f"## Test results — Round {round_idx}\n"
            f"HARNESS ERROR (does not reflect your code): {test_result['error']}\n"
        )
    passed = test_result.get("tests_passed", 0)
    failed = test_result.get("tests_failed", 0)
    if test_result.get("passed"):
        return (
            f"## Test results — Round {round_idx}\n"
            f"ALL TESTS PASSED ({passed} passed).\n"
        )
    output = test_result.get("output", "") or ""
    if len(output) > max_output_chars:
        output = "…(truncated)…\n" + output[-max_output_chars:]
    return (
        f"## Test results — Round {round_idx}\n"
        f"{passed} passed, {failed} failed.\n\n"
        f"Failing test output (tail):\n```\n{output}\n```\n"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/restart/test_feedback.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/cooperbench/restart/feedback.py tests/restart/test_feedback.py
git commit -m "restart: uniform test-feedback formatter (tail-truncated)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Policy logic — prompts, informed summary, starting patch (pure)

**Files:**
- Create: `src/cooperbench/restart/policies.py`
- Test: `tests/restart/test_policies.py`

**Interfaces:**
- Consumes: `format_feedback` (Task 2). History entries are dicts:
  `{"round": int, "patch": str, "tests": <run_patch_test dict>, "cost": float}`.
- Produces (used by loop, Task 5):
  - `POLICIES = ("iterate", "restart-fresh", "restart-informed", "agent-decides")`
  - `starting_patch_for_round(policy: str, history: list[dict]) -> str | None`
  - `build_round_task(policy: str, base_task: str, history: list[dict]) -> str`
  - `informed_summary(history: list[dict]) -> str` (harness-generated; never agent-authored — spec requirement)

- [ ] **Step 1: Write the failing test**

```python
# tests/restart/test_policies.py
import pytest

from cooperbench.restart.policies import (
    POLICIES,
    build_round_task,
    informed_summary,
    starting_patch_for_round,
)

H = [
    {"round": 1,
     "patch": "diff --git a/src/x.py b/src/x.py\n--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-a\n+b\n",
     "tests": {"passed": False, "tests_passed": 2, "tests_failed": 3,
               "output": "FAILED test_a - KeyError", "error": None},
     "cost": 0.05},
]
BASE = "## Your Task\nImplement feature X."


class TestStartingPatch:
    def test_round1_is_always_none(self):
        for p in POLICIES:
            assert starting_patch_for_round(p, []) is None

    def test_iterate_carries_last_patch(self):
        assert starting_patch_for_round("iterate", H) == H[-1]["patch"]
        assert starting_patch_for_round("agent-decides", H) == H[-1]["patch"]

    def test_restarts_return_none(self):
        assert starting_patch_for_round("restart-fresh", H) is None
        assert starting_patch_for_round("restart-informed", H) is None

    def test_unknown_policy_raises(self):
        with pytest.raises(ValueError):
            starting_patch_for_round("yolo", H)


class TestBuildRoundTask:
    def test_round1_is_base_task_for_all(self):
        for p in POLICIES:
            assert build_round_task(p, BASE, []) == BASE

    def test_fresh_never_sees_history(self):
        assert build_round_task("restart-fresh", BASE, H) == BASE

    def test_iterate_sees_feedback_and_worktree_note(self):
        t = build_round_task("iterate", BASE, H)
        assert "2 passed, 3 failed" in t and "FAILED test_a" in t
        assert "working tree" in t.lower()

    def test_informed_sees_lessons_but_no_worktree(self):
        t = build_round_task("restart-informed", BASE, H)
        assert "Attempt 1" in t and "2/5" in t
        assert "working tree" not in t.lower()
        assert "clean checkout" in t.lower()


class TestInformedSummary:
    def test_summarizes_counts_files_and_failures(self):
        s = informed_summary(H)
        assert "Attempt 1" in s and "2/5" in s
        assert "src/x.py" in s                 # touched files from the diff
        assert "FAILED test_a" in s            # failure tail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/restart/test_policies.py -q`
Expected: FAIL `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/cooperbench/restart/policies.py
"""What each policy carries between rounds.

Round 1 is identical for every policy (bare feature spec, clean tree).
From round 2 on, exactly one thing differs:
  iterate          -> code: last patch applied;  prompt: full round history
  restart-fresh    -> code: clean;               prompt: nothing (best-of-K)
  restart-informed -> code: clean;               prompt: harness-built lessons
  agent-decides    -> like iterate; the loop applies the decision (Task 6)
The informed summary is built by the harness from artifacts (never written
by the failing agent) so its quality is uniform across rounds and tiers.
"""

from cooperbench.agents._coop.territory import files_in_patch
from cooperbench.restart.feedback import format_feedback

POLICIES = ("iterate", "restart-fresh", "restart-informed", "agent-decides")


def _check(policy: str) -> None:
    if policy not in POLICIES:
        raise ValueError(f"unknown policy: {policy!r} (expected one of {POLICIES})")


def starting_patch_for_round(policy: str, history: list[dict]) -> str | None:
    _check(policy)
    if not history:
        return None
    if policy in ("iterate", "agent-decides"):
        return history[-1]["patch"] or None
    return None


def informed_summary(history: list[dict]) -> str:
    lines = ["## Lessons from previous attempts (auto-generated by the harness)"]
    for h in history:
        t = h["tests"]
        total = t.get("tests_passed", 0) + t.get("tests_failed", 0)
        files = ", ".join(sorted(files_in_patch(h["patch"]))) or "(no files changed)"
        tail = (t.get("output", "") or "")[-500:]
        lines.append(
            f"### Attempt {h['round']}: {t.get('tests_passed', 0)}/{total} tests passed\n"
            f"Files touched: {files}\n"
            f"Failure tail:\n```\n{tail}\n```"
        )
    lines.append(
        "You are starting from a CLEAN CHECKOUT (none of the code above is "
        "present). Use the lessons; write a fresh implementation."
    )
    return "\n\n".join(lines)


def build_round_task(policy: str, base_task: str, history: list[dict]) -> str:
    _check(policy)
    if not history or policy == "restart-fresh":
        return base_task
    if policy == "restart-informed":
        return f"{base_task}\n\n{informed_summary(history)}"
    # iterate / agent-decides: full history + the current tree carries the work
    blocks = [format_feedback(h["tests"], h["round"]) for h in history]
    return (
        f"{base_task}\n\n## Previous attempts\n"
        f"Your WORKING TREE already contains your latest attempt; refine it.\n\n"
        + "\n".join(blocks)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/restart/test_policies.py -q`
Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add src/cooperbench/restart/policies.py tests/restart/test_policies.py
git commit -m "restart: policy logic — starting patch + round prompts + informed summary

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Patch scope stripper + decision parser (pure, Phase 2)

**Files:**
- Create: `src/cooperbench/restart/decision.py`
- Test: `tests/restart/test_decision.py`

**Interfaces:**
- Consumes: `files_in_patch(patch) -> set[str]` from `cooperbench.agents._coop.territory`.
- Produces (used by loop in agent-decides mode):
  - `strip_paths_from_patch(patch: str, scope: str, path: str | None) -> str` — scope `"file"` drops that one file's diff section; `"directory"` drops every touched file under the path; `"all"` returns `""`.
  - `parse_decision(text: str) -> dict` — `{"action": "continue"}` or `{"action": "restart", "scope": "file|directory|all", "path": str|None}`; malformed input → `{"action": "continue", "parse_error": True}` (never crashes a run).
  - `build_decision_prompt(feedback: str, touched_files: list[str]) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/restart/test_decision.py
from cooperbench.restart.decision import (
    build_decision_prompt,
    parse_decision,
    strip_paths_from_patch,
)

PATCH = (
    "diff --git a/pkg/a.py b/pkg/a.py\n--- a/pkg/a.py\n+++ b/pkg/a.py\n@@ -1 +1 @@\n-x\n+y\n"
    "diff --git a/pkg/sub/b.py b/pkg/sub/b.py\n--- a/pkg/sub/b.py\n+++ b/pkg/sub/b.py\n@@ -1 +1 @@\n-p\n+q\n"
    "diff --git a/other/c.py b/other/c.py\n--- a/other/c.py\n+++ b/other/c.py\n@@ -1 +1 @@\n-m\n+n\n"
)


class TestStripPaths:
    def test_file_scope_drops_one_section(self):
        out = strip_paths_from_patch(PATCH, "file", "pkg/a.py")
        assert "pkg/a.py" not in out and "pkg/sub/b.py" in out and "other/c.py" in out

    def test_directory_scope_drops_subtree(self):
        out = strip_paths_from_patch(PATCH, "directory", "pkg")
        assert "pkg/a.py" not in out and "pkg/sub/b.py" not in out
        assert "other/c.py" in out

    def test_all_scope_empties(self):
        assert strip_paths_from_patch(PATCH, "all", None) == ""

    def test_ends_with_newline_when_nonempty(self):
        assert strip_paths_from_patch(PATCH, "file", "pkg/a.py").endswith("\n")


class TestParseDecision:
    def test_continue(self):
        assert parse_decision('{"action": "continue"}') == {"action": "continue"}

    def test_restart_with_fenced_json(self):
        d = parse_decision('```json\n{"action":"restart","scope":"file","path":"pkg/a.py"}\n```')
        assert d == {"action": "restart", "scope": "file", "path": "pkg/a.py"}

    def test_garbage_defaults_to_continue_flagged(self):
        d = parse_decision("hmm let me think")
        assert d["action"] == "continue" and d.get("parse_error") is True

    def test_bad_scope_defaults_to_continue_flagged(self):
        d = parse_decision('{"action":"restart","scope":"universe"}')
        assert d["action"] == "continue" and d.get("parse_error") is True


class TestBuildDecisionPrompt:
    def test_mentions_options_and_state(self):
        p = build_decision_prompt("2 passed, 3 failed", ["pkg/a.py"])
        assert "continue" in p and "restart" in p
        assert "pkg/a.py" in p and "2 passed, 3 failed" in p
        assert "legitimate" in p  # restart framed as legitimate, not failure
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/restart/test_decision.py -q`
Expected: FAIL `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/cooperbench/restart/decision.py
"""Phase-2 machinery: the agent's restart decision, parsed and applied.

The decision is a separate cheap model call between rounds (same model as
the working agent — it's that agent's metacognition being measured). The
harness applies the chosen scope by stripping diff sections; malformed
decisions degrade to "continue" (logged), never crash a run.
"""

import json
import re

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)
_SCOPES = ("file", "directory", "all")


def strip_paths_from_patch(patch: str, scope: str, path: str | None) -> str:
    if scope == "all":
        return ""
    sections = re.split(r"(?=^diff --git )", patch, flags=re.M)
    kept = []
    for s in sections:
        if not s.strip():
            continue
        m = re.match(r"diff --git a/(\S+) b/", s)
        f = m.group(1) if m else ""
        drop = (scope == "file" and f == path) or (
            scope == "directory" and (f == path or f.startswith(path.rstrip("/") + "/"))
        )
        if not drop:
            kept.append(s)
    out = "".join(kept)
    if out and not out.endswith("\n"):
        out += "\n"
    return out


def parse_decision(text: str) -> dict:
    raw = text.strip()
    m = _FENCE.search(raw)
    if m:
        raw = m.group(1)
    try:
        d = json.loads(raw)
        action = d.get("action")
        if action == "continue":
            return {"action": "continue"}
        if action == "restart" and d.get("scope") in _SCOPES:
            return {"action": "restart", "scope": d["scope"], "path": d.get("path")}
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    return {"action": "continue", "parse_error": True}


def build_decision_prompt(feedback: str, touched_files: list[str]) -> str:
    files = "\n".join(f"- {f}" for f in touched_files) or "- (none)"
    return (
        "You are working on a coding task in rounds. Your last attempt's test "
        f"results:\n\n{feedback}\n\nFiles you have modified so far:\n{files}\n\n"
        "Decide how to proceed. Restarting (discarding part or all of your "
        "work) is a legitimate, cost-free option when an approach looks like "
        "a dead end — not an admission of failure. Reply with ONLY a JSON "
        "object, one of:\n"
        '{"action": "continue"}\n'
        '{"action": "restart", "scope": "file", "path": "<one file above>"}\n'
        '{"action": "restart", "scope": "directory", "path": "<dir prefix>"}\n'
        '{"action": "restart", "scope": "all"}\n'
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/restart/test_decision.py -q`
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add src/cooperbench/restart/decision.py tests/restart/test_decision.py
git commit -m "restart: phase-2 decision parser + scoped patch stripper

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Loop orchestrator with injectable spawn/eval (unit-testable without docker)

**Files:**
- Create: `src/cooperbench/restart/loop.py`
- Test: `tests/restart/test_loop.py`

**Interfaces:**
- Consumes: Tasks 2–4 interfaces; `cooperbench.runner.coop._spawn_agent` (returns dict with keys `status, patch, cost, steps, messages`); `cooperbench.eval.sandbox.run_patch_test`.
- Produces: `execute_restart_loop(repo, task_id, feature_id, policy, run_name, model_name, rounds=4, backend="docker", dataset_dir=None, logs_dir=None, force=False, quiet=True, spawn_fn=None, eval_fn=None, decide_fn=None) -> dict` — the per-feature `result.json` content: `{"repo", "task_id", "feature_id", "policy", "model", "rounds_run", "solved", "solve_round", "total_cost", "rounds": [per-round summaries], "log_dir"}`. Artifacts written per Global Constraints. Resumable: completed rounds (with `tests.json`) are reloaded, not re-run; a feature with `result.json` and no `force` is skipped.

- [ ] **Step 1: Write the failing test**

```python
# tests/restart/test_loop.py
import json

from cooperbench.restart.loop import execute_restart_loop

PATCH_R = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-0\n+%d\n"


def make_fakes(pass_on_round=None, record=None):
    """spawn_fn returns a distinct patch per round; eval_fn passes on round N."""
    calls = {"n": 0}

    def spawn_fn(*, task_override, starting_patch, **kw):
        calls["n"] += 1
        if record is not None:
            record.append({"round": calls["n"], "task": task_override,
                           "starting_patch": starting_patch})
        return {"status": "Submitted", "patch": PATCH_R % calls["n"],
                "cost": 0.01, "steps": 3, "messages": []}

    def eval_fn(repo, task_id, feature_id, patch, **kw):
        ok = pass_on_round is not None and calls["n"] >= pass_on_round
        return {"passed": ok, "tests_passed": 5 if ok else 2,
                "tests_failed": 0 if ok else 3,
                "output": "ok" if ok else "FAILED test_x", "error": None}

    return spawn_fn, eval_fn


def run(tmp_path, policy, pass_on_round=None, rounds=4, record=None, decide_fn=None):
    # base task file the loop reads
    fdir = tmp_path / "ds" / "repo_x" / "task1" / "feature2"
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / "feature.md").write_text("## Your Task\nDo X.")
    spawn_fn, eval_fn = make_fakes(pass_on_round, record)
    return execute_restart_loop(
        "repo_x", 1, 2, policy, run_name="T", model_name="fake",
        rounds=rounds, dataset_dir=tmp_path / "ds", logs_dir=tmp_path / "logs",
        spawn_fn=spawn_fn, eval_fn=eval_fn, decide_fn=decide_fn,
    )


class TestLoopCore:
    def test_early_stop_on_pass(self, tmp_path):
        r = run(tmp_path, "iterate", pass_on_round=2)
        assert r["solved"] is True and r["solve_round"] == 2 and r["rounds_run"] == 2

    def test_exhausts_k_rounds_without_pass(self, tmp_path):
        r = run(tmp_path, "restart-fresh", pass_on_round=None)
        assert r["solved"] is False and r["rounds_run"] == 4

    def test_artifacts_written_per_round(self, tmp_path):
        run(tmp_path, "iterate", pass_on_round=None, rounds=2)
        base = tmp_path / "logs" / "T" / "restart" / "repo_x" / "1" / "f2"
        for n in (1, 2):
            assert (base / f"round_{n}" / "attempt.patch").exists()
            assert (base / f"round_{n}" / "tests.json").exists()
            assert (base / f"round_{n}" / "feedback.txt").exists()
            assert (base / f"round_{n}" / "agent.json").exists()
        assert json.loads((base / "result.json").read_text())["rounds_run"] == 2


class TestPolicyWiring:
    def test_iterate_carries_patch_fresh_does_not(self, tmp_path):
        rec = []
        run(tmp_path, "iterate", rounds=2, record=rec)
        assert rec[0]["starting_patch"] is None
        assert rec[1]["starting_patch"] == PATCH_R % 1
        rec2 = []
        run(tmp_path.joinpath("b"), "restart-fresh", rounds=2, record=rec2)
        assert rec2[1]["starting_patch"] is None
        assert rec2[1]["task"] == rec2[0]["task"]  # fresh: identical prompt

    def test_informed_prompt_has_lessons(self, tmp_path):
        rec = []
        run(tmp_path, "restart-informed", rounds=2, record=rec)
        assert "Lessons from previous attempts" in rec[1]["task"]


class TestResume:
    def test_completed_feature_is_skipped(self, tmp_path):
        run(tmp_path, "iterate", pass_on_round=1)
        rec = []
        r2 = run(tmp_path, "iterate", pass_on_round=1, record=rec)
        assert r2.get("skipped") is True and rec == []


class TestAgentDecides:
    def test_restart_all_clears_starting_patch(self, tmp_path):
        rec = []
        decide = lambda feedback, files: {"action": "restart", "scope": "all", "path": None}
        run(tmp_path, "agent-decides", rounds=2, record=rec, decide_fn=decide)
        assert rec[1]["starting_patch"] is None  # decision applied
        base = tmp_path / "logs" / "T" / "restart" / "repo_x" / "1" / "f2"
        d = json.loads((base / "round_2" / "decision.json").read_text())
        assert d["action"] == "restart" and d["scope"] == "all"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/restart/test_loop.py -q`
Expected: FAIL `ImportError`

- [ ] **Step 3: Write the implementation**

```python
# src/cooperbench/restart/loop.py
"""Round loop: attempt -> visible tests -> (policy) -> next round.

The loop evaluates each round itself (run_patch_test), so the final verdict
is just "did any round pass" — there is no separate eval routing to get
wrong. spawn/eval/decide are injectable for docker-free unit tests; the
defaults wire the real harness.
"""

import json
from datetime import datetime
from pathlib import Path

from cooperbench.agents._coop.territory import files_in_patch
from cooperbench.restart.decision import (
    build_decision_prompt,
    parse_decision,
    strip_paths_from_patch,
)
from cooperbench.restart.feedback import format_feedback
from cooperbench.restart.policies import build_round_task, starting_patch_for_round
from cooperbench.runner.tasks import DEFAULT_DATASET_DIR, DEFAULT_LOGS_DIR


def _real_spawn(**kw):
    from cooperbench.runner.coop import _spawn_agent

    return _spawn_agent(**kw)


def _real_eval(repo, task_id, feature_id, patch, backend="docker", dataset_dir=None):
    from cooperbench.eval.sandbox import run_patch_test

    return run_patch_test(repo, task_id, feature_id, agent_patch=patch or None,
                          backend=backend, dataset_dir=dataset_dir)


def _real_decide(model_name):
    def decide(feedback: str, touched: list[str]) -> dict:
        import litellm

        prompt = build_decision_prompt(feedback, touched)
        try:
            resp = litellm.completion(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                timeout=120,
            )
            return parse_decision(resp.choices[0].message.content or "")
        except Exception as e:  # decision failure must not kill the run
            return {"action": "continue", "parse_error": True, "error": str(e)[:200]}

    return decide


def execute_restart_loop(
    repo: str,
    task_id: int,
    feature_id: int,
    policy: str,
    run_name: str,
    model_name: str,
    rounds: int = 4,
    backend: str = "docker",
    dataset_dir: Path | str | None = None,
    logs_dir: Path | str | None = None,
    force: bool = False,
    quiet: bool = True,
    spawn_fn=None,
    eval_fn=None,
    decide_fn=None,
) -> dict:
    root = Path(dataset_dir) if dataset_dir is not None else DEFAULT_DATASET_DIR
    logs_root = Path(logs_dir) if logs_dir is not None else DEFAULT_LOGS_DIR
    log_dir = logs_root / run_name / "restart" / repo / str(task_id) / f"f{feature_id}"
    result_file = log_dir / "result.json"
    if result_file.exists() and not force:
        return {"skipped": True, **json.loads(result_file.read_text())}

    spawn_fn = spawn_fn or _real_spawn
    eval_fn = eval_fn or _real_eval
    if policy == "agent-decides" and decide_fn is None:
        decide_fn = _real_decide(model_name)

    base_task = (root / repo / f"task{task_id}" / f"feature{feature_id}" / "feature.md").read_text()
    log_dir.mkdir(parents=True, exist_ok=True)

    # resume: reload completed rounds from artifacts
    history: list[dict] = []
    for n in range(1, rounds + 1):
        rd = log_dir / f"round_{n}"
        if (rd / "tests.json").exists() and (rd / "attempt.patch").exists():
            history.append({
                "round": n,
                "patch": (rd / "attempt.patch").read_text(),
                "tests": json.loads((rd / "tests.json").read_text()),
                "cost": json.loads((rd / "agent.json").read_text()).get("cost", 0),
            })
        else:
            break

    solved = any(h["tests"].get("passed") for h in history)
    start = datetime.now()

    while not solved and len(history) < rounds:
        n = len(history) + 1
        rd = log_dir / f"round_{n}"
        rd.mkdir(parents=True, exist_ok=True)

        starting_patch = starting_patch_for_round(policy, history)
        task = build_round_task(policy, base_task, history)

        # agent-decides: ask the SAME model whether to keep or strip its work
        if policy == "agent-decides" and history:
            fb = format_feedback(history[-1]["tests"], history[-1]["round"])
            touched = sorted(files_in_patch(history[-1]["patch"]))
            decision = decide_fn(fb, touched)
            (rd / "decision.json").write_text(json.dumps(decision, indent=2))
            if decision.get("action") == "restart":
                starting_patch = strip_paths_from_patch(
                    starting_patch or "", decision["scope"], decision.get("path")
                ) or None

        agent = spawn_fn(
            repo_name=repo, task_id=task_id, feature_id=feature_id,
            agent_name="mini_swe_agent_v2", model_name=model_name,
            agent_id="restart_agent", agents=["restart_agent"],
            redis_url=None, git_server_url=None, git_enabled=False,
            git_network=None, messaging_enabled=False, quiet=quiet,
            backend=backend, agent_config=None, run_name=None,
            features=[feature_id], dataset_dir=dataset_dir, logs_dir=logs_dir,
            starting_patch=starting_patch, task_override=task,
        )
        patch = agent.get("patch", "") or ""
        tests = eval_fn(repo, task_id, feature_id, patch,
                        backend=backend, dataset_dir=dataset_dir)

        (rd / "attempt.patch").write_text(patch)
        (rd / "tests.json").write_text(json.dumps(tests, indent=2))
        (rd / "feedback.txt").write_text(format_feedback(tests, n))
        (rd / "agent.json").write_text(json.dumps(
            {"status": agent.get("status"), "cost": agent.get("cost", 0),
             "steps": agent.get("steps", 0)}, indent=2))

        history.append({"round": n, "patch": patch, "tests": tests,
                        "cost": agent.get("cost", 0)})
        solved = bool(tests.get("passed"))

    solve_round = next((h["round"] for h in history if h["tests"].get("passed")), None)
    result = {
        "repo": repo, "task_id": task_id, "feature_id": feature_id,
        "policy": policy, "model": model_name,
        "rounds_run": len(history), "solved": solved, "solve_round": solve_round,
        "total_cost": sum(h["cost"] for h in history),
        "rounds": [
            {"round": h["round"], "passed": h["tests"].get("passed"),
             "tests_passed": h["tests"].get("tests_passed"),
             "tests_failed": h["tests"].get("tests_failed"),
             "cost": h["cost"]}
            for h in history
        ],
        "started_at": start.isoformat(), "ended_at": datetime.now().isoformat(),
        "log_dir": str(log_dir),
    }
    result_file.write_text(json.dumps(result, indent=2))
    return result
```

- [ ] **Step 4: Run tests to verify they pass (and no regression)**

Run: `.venv/bin/pytest tests/restart/ -q`
Expected: all pass (Tasks 1–5 suites)

- [ ] **Step 5: Commit**

```bash
git add src/cooperbench/restart/loop.py tests/restart/test_loop.py
git commit -m "restart: loop orchestrator — injectable spawn/eval, per-round artifacts, resume

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: CLI entry `restart_run.py`

**Files:**
- Create: `restart_run.py` (repo root, like `reeval.py`)

**Interfaces:**
- Consumes: `build_feature_pool` (Task 1), `execute_restart_loop` (Task 5), `POLICIES` (Task 3).
- Produces: command-line runner used by all batch scripts:
  `.venv/bin/python restart_run.py --run-name R-mini-iterate --model azure/gpt-5.4-mini --policy iterate [--rounds 4] [--subset flash_amd64] [--concurrency 2] [--limit N] [--only repo:task:fid,...] [--force] [--dry-run]`

- [ ] **Step 1: Write the implementation** (thin I/O wrapper — validated by `--dry-run` instead of unit tests)

```python
# restart_run.py
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
```

- [ ] **Step 2: Validate with dry-run (no docker, no Azure)**

Run: `.venv/bin/python restart_run.py --run-name X --model fake --policy iterate --dry-run --limit 3`
Expected: header line `3 features × policy=iterate × K=4` + 3 feature lines, exit 0.

Run: `.venv/bin/python restart_run.py --run-name X --model fake --policy yolo --dry-run 2>&1 | tail -1`
Expected: argparse error listing valid policies, exit ≠ 0.

- [ ] **Step 3: Commit**

```bash
git add restart_run.py
git commit -m "restart: CLI runner over the feature pool (resumable, dry-run)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Docker smoke — 1 feature, K=2, mini (~$0.10-0.20 Azure / $0 Modal)

**Files:**
- No new files; this validates Tasks 1–6 end-to-end on real infra.

**Interfaces:**
- Consumes: everything above, plus real docker + Azure.
- Produces: go/no-go for the wiring; any fix found here is committed before proceeding.

- [ ] **Step 1: Run the smoke (announce cost estimate first, per standing rule)**

```bash
cd /Users/javieraguilarmartin1/Documents/repos/CooperBench
source azure_env.sh
export MSWEA_GLOBAL_COST_LIMIT=25
.venv/bin/python restart_run.py --run-name SMOKE-restart \
  --model azure/gpt-5.4-mini --policy iterate --rounds 2 \
  --only samuelcolvin_dirty_equals_task:43:2 --concurrency 1 --force
```
Expected: 1 feature line ending `solved=<bool> rounds=<1|2> $<cost>`.

- [ ] **Step 2: Verify the artifacts are complete and coherent**

```bash
B=logs/SMOKE-restart/restart/samuelcolvin_dirty_equals_task/43/f2
ls $B/round_1/  # attempt.patch tests.json feedback.txt agent.json
python3 - <<'EOF'
import json
r = json.load(open("logs/SMOKE-restart/restart/samuelcolvin_dirty_equals_task/43/f2/result.json"))
assert r["policy"] == "iterate" and r["rounds_run"] in (1, 2), r
assert isinstance(r["total_cost"], float) and r["total_cost"] > 0
print("SMOKE OK:", {k: r[k] for k in ("solved", "solve_round", "rounds_run", "total_cost")})
EOF
```
Expected: `SMOKE OK: {...}`. If round 2 ran, additionally check `round_2` exists and, for iterate, that the agent saw feedback: `grep -l "Test results" $B/round_2/../round_1/feedback.txt`.

- [ ] **Step 3: Verify resume**

Re-run the Step-1 command **without** `--force`.
Expected: same feature reports `SKIP` and no new docker containers start.

- [ ] **Step 4: Commit any fixes surfaced by the smoke**

```bash
git add -A src/cooperbench/restart tests/restart restart_run.py
git commit -m "restart: smoke-run fixes (real docker + Azure wiring)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
(Skip the commit if the smoke passed with no changes.)

---

### Task 8: Metrics aggregator `restart_metrics.py`

**Files:**
- Create: `restart_metrics.py` (repo root)
- Test: `tests/restart/test_metrics.py`

**Interfaces:**
- Consumes: the artifact tree from Task 5 (Global Constraints layout).
- Produces:
  - Pure functions (imported by tests): `curve(rounds: list[dict]) -> list[int]` (tests_passed per round), `is_plateau(c: list[int], window: int = 2) -> bool` (no strict gain across the last `window` steps and did not end passed), `mcnemar(b: int, c: int) -> float` (exact, same as `seed_stats.py`).
  - CLI: `.venv/bin/python restart_metrics.py --runs R-mini-iterate,R-mini-restart-fresh [--gate]` → per-run pass rate, mean rounds/$-to-solve, plateau count; paired McNemar between every run pair sharing a tier; `--gate` prints the pilot verdict (first-round solve rate and plateau share with the spec thresholds: useful zone = first-round solve 20-60% AND ≥1 plateau observed).

- [ ] **Step 1: Write the failing test (pure pieces only)**

```python
# tests/restart/test_metrics.py
from restart_metrics import curve, is_plateau, mcnemar


class TestCurve:
    def test_extracts_tests_passed_sequence(self):
        rounds = [{"round": 1, "tests_passed": 2, "passed": False},
                  {"round": 2, "tests_passed": 4, "passed": False}]
        assert curve(rounds) == [2, 4]


class TestPlateau:
    def test_flat_tail_is_plateau(self):
        assert is_plateau([2, 3, 3, 3]) is True

    def test_still_growing_is_not(self):
        assert is_plateau([1, 2, 3, 4]) is False

    def test_solved_run_is_never_plateau(self):
        assert is_plateau([2, 5, 5], solved=True) is False

    def test_too_short_is_not(self):
        assert is_plateau([2]) is False


class TestMcNemar:
    def test_matches_known_values(self):
        assert mcnemar(0, 0) == 1.0
        assert abs(mcnemar(8, 1) - 0.0390625) < 1e-6  # 2*(9C0+9C1)/2^9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/restart/test_metrics.py -q`
Expected: FAIL `ImportError` (repo root not on path for tests → add path insert in the test's conftest if needed; simplest is `tests/restart/conftest.py` with `sys.path.insert(0, str(Path(__file__).parents[2]))`).

- [ ] **Step 3: Write the implementation**

```python
# restart_metrics.py
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
        d = json.load(open(p))
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
```

Also create `tests/restart/conftest.py`:

```python
# tests/restart/conftest.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))  # repo root for restart_metrics
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/restart/test_metrics.py -q`
Expected: `6 passed`

- [ ] **Step 5: Sanity-check the CLI on the smoke run**

Run: `.venv/bin/python restart_metrics.py --runs SMOKE-restart`
Expected: one summary line, no traceback.

- [ ] **Step 6: Commit**

```bash
git add restart_metrics.py tests/restart/test_metrics.py tests/restart/conftest.py
git commit -m "restart: metrics aggregator — curves, plateau, McNemar, pilot gate

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Batch scripts (pilot + phases)

**Files:**
- Create: `restart_pilot.sh`, `restart_phase1.sh`, `restart_phase2.sh`

**Interfaces:**
- Consumes: `restart_run.py` CLI (Task 6), `restart_metrics.py --gate` (Task 8).
- Produces: the staged runs from the spec. Run names are load-bearing for metrics: `R-<tier>-<policy>[-sN]`.

- [ ] **Step 1: Write the three scripts**

```bash
# restart_pilot.sh
#!/bin/bash
# Stage 0 pilot gate (~$7 Azure / $0 Modal, 1-2 h): 6 features ×
# {iterate, restart-fresh} × strong tier × K=4, then the gate verdict.
set -u
cd "$(dirname "$0")"
export MSWEA_GLOBAL_COST_LIMIT=25
run() {
  echo "=== $(date '+%m-%d %H:%M') START $1 (policy=$2) ==="
  .venv/bin/python restart_run.py --run-name "$1" --model azure/gpt-5.4 \
    --policy "$2" --rounds 4 --limit 6 --concurrency 2
  echo "=== $(date '+%m-%d %H:%M') DONE $1 ==="
}
run R-large-iterate-pilot iterate
run R-large-restart-fresh-pilot restart-fresh
.venv/bin/python restart_metrics.py \
  --runs R-large-iterate-pilot,R-large-restart-fresh-pilot --gate
```

```bash
# restart_phase1.sh
#!/bin/bash
# Stage 1 (~$35-45 Azure / $0 Modal, 8-12 h): full pool × 3 policies × 2 tiers.
# Resumable; relaunch after interruptions. Usage: source azure_env.sh && bash restart_phase1.sh
set -u
cd "$(dirname "$0")"
export MSWEA_GLOBAL_COST_LIMIT=25
for tier_model in "mini azure/gpt-5.4-mini" "large azure/gpt-5.4"; do
  set -- $tier_model
  for policy in iterate restart-fresh restart-informed; do
    echo "=== $(date '+%m-%d %H:%M') START R-$1-$policy ==="
    .venv/bin/python restart_run.py --run-name "R-$1-$policy" --model "$2" \
      --policy "$policy" --rounds 4 --concurrency 2
    echo "=== $(date '+%m-%d %H:%M') DONE R-$1-$policy ==="
  done
done
echo "=== PHASE 1 COMPLETE ==="
```

```bash
# restart_phase2.sh
#!/bin/bash
# Stage 2 (~$15-20 Azure / $0 Modal, 4-6 h): agent-decides × 2 tiers.
set -u
cd "$(dirname "$0")"
export MSWEA_GLOBAL_COST_LIMIT=25
for tier_model in "mini azure/gpt-5.4-mini" "large azure/gpt-5.4"; do
  set -- $tier_model
  echo "=== $(date '+%m-%d %H:%M') START R-$1-agent-decides ==="
  .venv/bin/python restart_run.py --run-name "R-$1-agent-decides" --model "$2" \
    --policy agent-decides --rounds 4 --concurrency 2
  echo "=== $(date '+%m-%d %H:%M') DONE R-$1-agent-decides ==="
done
echo "=== PHASE 2 COMPLETE ==="
```

- [ ] **Step 2: Syntax-check without spending**

Run: `bash -n restart_pilot.sh && bash -n restart_phase1.sh && bash -n restart_phase2.sh && echo SYNTAX_OK`
Expected: `SYNTAX_OK`

- [ ] **Step 3: Commit**

```bash
git add restart_pilot.sh restart_phase1.sh restart_phase2.sh
git commit -m "restart: staged batch scripts (pilot gate, phase 1, phase 2)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Adversarial audit checkpoint (before trusting Phase-1 numbers; $0)

**Files:**
- No code. Process step mandated by the spec ("same rigor as article 1").

**Interfaces:**
- Consumes: everything committed in Tasks 1–9 plus the pilot's artifacts.
- Produces: an audit verdict recorded in `experiment/RESTART_DESIGN.md` (append a "## Audit outcome" section) before `restart_phase1.sh` is launched at full scale.

- [ ] **Step 1: Dispatch an independent adversarial reviewer agent** with this brief: audit `src/cooperbench/restart/` + `restart_run.py` + `restart_metrics.py` hunting composition/routing bugs, with special attention to the recurring class: *what state does each round actually apply and measure* — (a) does RESTART-FRESH round N really start from base (no starting_patch leakage)? (b) does ITERATE round N really contain round N-1's diff (starting_patch applied + committed by the adapter, and the agent's final `git diff` therefore cumulative — check `apply_patch_in_container` semantics)? (c) does `run_patch_test` in-round receive the FULL cumulative patch, not just the round's delta? (d) resume: does a resumed feature rebuild `history` identical to the uninterrupted run? (e) agent-decides: is the stripped patch what actually reaches the container?
- [ ] **Step 2: Verify claims empirically on the pilot artifacts** (patch SHAs/content across rounds, as article 1 did with SHA chaining) — pick 2 pilot features and diff `round_1/attempt.patch` vs `round_2/attempt.patch` under ITERATE: round 2 must be a superset-from-base (contains round 1's hunks or their evolution), and under RESTART-FRESH: round 2 must NOT presuppose round 1.
- [ ] **Step 3: Fix anything CRITICAL/MAJOR found, with a test reproducing it first (TDD), commit, and re-run the pilot cells the bug could have contaminated ($≤7).**
- [ ] **Step 4: Append the audit outcome to `experiment/RESTART_DESIGN.md` and commit.**

```bash
git add experiment/RESTART_DESIGN.md
git commit -m "docs: restart-loop audit outcome (pre-phase-1 gate)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Execution order and gates

1. Tasks 1–6 (code, ~all TDD, no spend) → 7 (smoke, ~$0.20) → 8–9 (code, no spend).
2. `restart_pilot.sh` (~$7) → **gate verdict** (Task 8's `--gate`).
3. Task 10 audit ($0) on pilot artifacts → fix/re-run if needed.
4. Only then `restart_phase1.sh` (~$35-45) → analysis → `restart_phase2.sh` (~$15-20) → seeds (re-run phase scripts with `-s2`/`-s3` suffixed run names) (~$20-25).
5. Article drafting starts after Phase 1 lands (fresh blog branch from up-to-date main).

## Self-review notes (done)

- **Spec coverage**: pool ✓(T1), uniform feedback ✓(T2), 3 policies + informed-by-harness ✓(T3), scope tool + parse ✓(T4), K/early-stop/resume/artifacts ✓(T5), equal-compute caps ✓(env in scripts, T9), pilot gate thresholds ✓(T8 `--gate`), audit ✓(T10), estimates rule ✓(headers in T9 scripts + T7 step 1). Phase-2 calibration metric is *analysis* over persisted artifacts (labels from Phase-1 runs + decisions from Phase-2 `decision.json`) — no extra harness code needed; computed at article-analysis time with `restart_metrics.py` extensions if useful.
- **Placeholder scan**: none — every code step has full code; T10 is process by design.
- **Type consistency**: history entry shape `{round, patch, tests, cost}` consistent across T3/T5; `run_patch_test` dict keys (`passed, tests_passed, tests_failed, output, error`) consistent across T2/T5/T8; `POLICIES` names consistent across T3/T5/T6/T9.
