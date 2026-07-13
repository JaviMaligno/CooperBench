import json

from cooperbench.restart.loop import execute_restart_loop

PATCH_R = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-0\n+%d\n"


def make_fakes(pass_on_round=None, record=None):
    calls = {"n": 0}

    def spawn_fn(*, task_override, starting_patch, **kwargs):
        calls["n"] += 1
        if record is not None:
            record.append({"round": calls["n"], "task": task_override,
                           "starting_patch": starting_patch})
        return {"status": "Submitted", "patch": PATCH_R % calls["n"],
                "cost": 0.01, "steps": 3, "messages": []}

    def eval_fn(repo, task_id, feature_id, patch, **kwargs):
        passed = pass_on_round is not None and calls["n"] >= pass_on_round
        return {"passed": passed, "tests_passed": 5 if passed else 2,
                "tests_failed": 0 if passed else 3,
                "output": "ok" if passed else "FAILED test_x", "error": None}
    return spawn_fn, eval_fn


def run(tmp_path, policy, pass_on_round=None, rounds=4, record=None, decide_fn=None):
    feature_dir = tmp_path / "ds" / "repo_x" / "task1" / "feature2"
    feature_dir.mkdir(parents=True, exist_ok=True)
    (feature_dir / "feature.md").write_text("## Your Task\nDo X.")
    spawn_fn, eval_fn = make_fakes(pass_on_round, record)
    return execute_restart_loop(
        "repo_x", 1, 2, policy, run_name="T", model_name="fake",
        rounds=rounds, dataset_dir=tmp_path / "ds", logs_dir=tmp_path / "logs",
        spawn_fn=spawn_fn, eval_fn=eval_fn, decide_fn=decide_fn,
    )


class TestLoopCore:
    def test_early_stop_on_pass(self, tmp_path):
        result = run(tmp_path, "iterate", pass_on_round=2)
        assert result["solved"] is True and result["solve_round"] == 2
        assert result["rounds_run"] == 2

    def test_exhausts_k_rounds_without_pass(self, tmp_path):
        result = run(tmp_path, "restart-fresh", pass_on_round=None)
        assert result["solved"] is False and result["rounds_run"] == 4

    def test_artifacts_written_per_round(self, tmp_path):
        run(tmp_path, "iterate", pass_on_round=None, rounds=2)
        base = tmp_path / "logs" / "T" / "restart" / "repo_x" / "1" / "f2"
        for round_idx in (1, 2):
            for name in ("attempt.patch", "tests.json", "feedback.txt", "agent.json", "cumulative.patch"):
                assert (base / f"round_{round_idx}" / name).exists()
        assert json.loads((base / "result.json").read_text())["rounds_run"] == 2


class TestPolicyWiring:
    def test_iterate_carries_patch_fresh_does_not(self, tmp_path):
        record = []
        run(tmp_path, "iterate", rounds=2, record=record)
        assert record[0]["starting_patch"] is None
        # After fix: single-entry concat = normalized patch
        assert record[1]["starting_patch"] == (PATCH_R % 1).rstrip("\n") + "\n"
        fresh_record = []
        run(tmp_path / "b", "restart-fresh", rounds=2, record=fresh_record)
        assert fresh_record[1]["starting_patch"] is None
        assert fresh_record[1]["task"] == fresh_record[0]["task"]

    def test_informed_prompt_has_lessons(self, tmp_path):
        record = []
        run(tmp_path, "restart-informed", rounds=2, record=record)
        assert "Lessons from previous attempts" in record[1]["task"]

    def test_iterate_round3_spawn_gets_cumulative(self, tmp_path):
        """Round 3 spawn receives concat of r1 + r2 patches as starting_patch."""
        record = []
        run(tmp_path, "iterate", rounds=3, record=record)
        # Round 1: no starting patch
        assert record[0]["starting_patch"] is None
        # Round 2: concat of [r1_patch] — single item normalized
        r1 = PATCH_R % 1
        assert record[1]["starting_patch"] == r1.rstrip("\n") + "\n"
        # Round 3: concat of [r1_patch, r2_patch]
        r2 = PATCH_R % 2
        expected = r1.rstrip("\n") + "\n" + r2.rstrip("\n") + "\n"
        assert record[2]["starting_patch"] == expected

    def test_iterate_round2_eval_uses_cumulative(self, tmp_path):
        """eval_fn for round 2 receives concat(r1, r2) — the cumulative tree."""
        eval_patches = []

        feature_dir = tmp_path / "ds" / "repo_x" / "task1" / "feature2"
        feature_dir.mkdir(parents=True, exist_ok=True)
        (feature_dir / "feature.md").write_text("## Your Task\nDo X.")

        calls = {"n": 0}
        def spawn_fn(*, task_override, starting_patch, **kwargs):
            calls["n"] += 1
            return {"status": "Submitted", "patch": PATCH_R % calls["n"],
                    "cost": 0.01, "steps": 3, "messages": []}

        def eval_fn(repo, task_id, feature_id, patch, **kwargs):
            eval_patches.append(patch)
            return {"passed": False, "tests_passed": 1, "tests_failed": 2,
                    "output": "FAILED", "error": None}

        execute_restart_loop(
            "repo_x", 1, 2, "iterate", run_name="T", model_name="fake",
            rounds=2, dataset_dir=tmp_path / "ds", logs_dir=tmp_path / "logs",
            spawn_fn=spawn_fn, eval_fn=eval_fn,
        )
        # Round 1: eval receives just r1 patch (no prior history)
        assert eval_patches[0] == PATCH_R % 1
        # Round 2: eval receives concat(r1, r2) — the cumulative tree
        r1 = PATCH_R % 1
        r2 = PATCH_R % 2
        expected_r2 = r1.rstrip("\n") + "\n" + r2.rstrip("\n") + "\n"
        assert eval_patches[1] == expected_r2

    def test_cumulative_patch_artifact_written(self, tmp_path):
        """cumulative.patch artifact is written and matches what eval_fn received."""
        eval_patches = []

        feature_dir = tmp_path / "ds" / "repo_x" / "task1" / "feature2"
        feature_dir.mkdir(parents=True, exist_ok=True)
        (feature_dir / "feature.md").write_text("## Your Task\nDo X.")

        calls = {"n": 0}
        def spawn_fn(*, task_override, starting_patch, **kwargs):
            calls["n"] += 1
            return {"status": "Submitted", "patch": PATCH_R % calls["n"],
                    "cost": 0.01, "steps": 3, "messages": []}

        def eval_fn(repo, task_id, feature_id, patch, **kwargs):
            eval_patches.append(patch)
            return {"passed": False, "tests_passed": 1, "tests_failed": 2,
                    "output": "FAILED", "error": None}

        execute_restart_loop(
            "repo_x", 1, 2, "iterate", run_name="T2", model_name="fake",
            rounds=2, dataset_dir=tmp_path / "ds", logs_dir=tmp_path / "logs",
            spawn_fn=spawn_fn, eval_fn=eval_fn,
        )
        base = tmp_path / "logs" / "T2" / "restart" / "repo_x" / "1" / "f2"
        # cumulative.patch for round 2 must exist and match what eval_fn received
        r2_cumulative = (base / "round_2" / "cumulative.patch").read_text()
        assert r2_cumulative == eval_patches[1]

    def test_fresh_still_evaluates_round_delta_only(self, tmp_path):
        """For fresh/informed, eval receives only the round's patch (no prior cumulation)."""
        eval_patches = []

        feature_dir = tmp_path / "ds" / "repo_x" / "task1" / "feature2"
        feature_dir.mkdir(parents=True, exist_ok=True)
        (feature_dir / "feature.md").write_text("## Your Task\nDo X.")

        calls = {"n": 0}
        def spawn_fn(*, task_override, starting_patch, **kwargs):
            calls["n"] += 1
            return {"status": "Submitted", "patch": PATCH_R % calls["n"],
                    "cost": 0.01, "steps": 3, "messages": []}

        def eval_fn(repo, task_id, feature_id, patch, **kwargs):
            eval_patches.append(patch)
            return {"passed": False, "tests_passed": 1, "tests_failed": 2,
                    "output": "FAILED", "error": None}

        execute_restart_loop(
            "repo_x", 1, 2, "restart-fresh", run_name="Tf", model_name="fake",
            rounds=2, dataset_dir=tmp_path / "ds", logs_dir=tmp_path / "logs",
            spawn_fn=spawn_fn, eval_fn=eval_fn,
        )
        # Round 1: just r1 patch
        assert eval_patches[0] == PATCH_R % 1
        # Round 2: just r2 patch (fresh — no cumulation)
        assert eval_patches[1] == PATCH_R % 2


class TestResume:
    def test_completed_feature_is_skipped(self, tmp_path):
        run(tmp_path, "iterate", pass_on_round=1)
        record = []
        result = run(tmp_path, "iterate", pass_on_round=1, record=record)
        assert result.get("skipped") is True and record == []


class TestAgentDecides:
    def test_restart_all_clears_starting_patch(self, tmp_path):
        record = []
        decide = lambda feedback, files: {"action": "restart", "scope": "all", "path": None}
        run(tmp_path, "agent-decides", rounds=2, record=record, decide_fn=decide)
        assert record[1]["starting_patch"] is None
        base = tmp_path / "logs" / "T" / "restart" / "repo_x" / "1" / "f2"
        decision = json.loads((base / "round_2" / "decision.json").read_text())
        assert decision["action"] == "restart" and decision["scope"] == "all"
