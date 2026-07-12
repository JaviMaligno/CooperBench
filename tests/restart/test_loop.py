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
            for name in ("attempt.patch", "tests.json", "feedback.txt", "agent.json"):
                assert (base / f"round_{round_idx}" / name).exists()
        assert json.loads((base / "result.json").read_text())["rounds_run"] == 2


class TestPolicyWiring:
    def test_iterate_carries_patch_fresh_does_not(self, tmp_path):
        record = []
        run(tmp_path, "iterate", rounds=2, record=record)
        assert record[0]["starting_patch"] is None
        assert record[1]["starting_patch"] == PATCH_R % 1
        fresh_record = []
        run(tmp_path / "b", "restart-fresh", rounds=2, record=fresh_record)
        assert fresh_record[1]["starting_patch"] is None
        assert fresh_record[1]["task"] == fresh_record[0]["task"]

    def test_informed_prompt_has_lessons(self, tmp_path):
        record = []
        run(tmp_path, "restart-informed", rounds=2, record=record)
        assert "Lessons from previous attempts" in record[1]["task"]


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
