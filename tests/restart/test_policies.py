import pytest

from cooperbench.restart.policies import (
    POLICIES, build_round_task, informed_summary, starting_patch_for_round,
)

H = [{"round": 1,
      "patch": "diff --git a/src/x.py b/src/x.py\n--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-a\n+b\n",
      "tests": {"passed": False, "tests_passed": 2, "tests_failed": 3,
                "output": "FAILED test_a - KeyError", "error": None},
      "cost": 0.05}]
BASE = "## Your Task\nImplement feature X."


class TestStartingPatch:
    def test_round1_is_always_none(self):
        for policy in POLICIES:
            assert starting_patch_for_round(policy, []) is None

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
        for policy in POLICIES:
            assert build_round_task(policy, BASE, []) == BASE

    def test_fresh_never_sees_history(self):
        assert build_round_task("restart-fresh", BASE, H) == BASE

    def test_iterate_sees_feedback_and_worktree_note(self):
        task = build_round_task("iterate", BASE, H)
        assert "2 passed, 3 failed" in task and "FAILED test_a" in task
        assert "working tree" in task.lower()

    def test_informed_sees_lessons_but_no_worktree(self):
        task = build_round_task("restart-informed", BASE, H)
        assert "Attempt 1" in task and "2/5" in task
        assert "working tree" not in task.lower()
        assert "clean checkout" in task.lower()


class TestInformedSummary:
    def test_summarizes_counts_files_and_failures(self):
        summary = informed_summary(H)
        assert "Attempt 1" in summary and "2/5" in summary
        assert "src/x.py" in summary
        assert "FAILED test_a" in summary
