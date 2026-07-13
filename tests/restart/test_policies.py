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

H2 = [
    {"round": 1,
     "patch": "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-0\n+1\n",
     "tests": {"passed": False, "tests_passed": 1, "tests_failed": 2,
               "output": "FAILED", "error": None},
     "cost": 0.01},
    {"round": 2,
     "patch": "diff --git a/g.py b/g.py\n--- a/g.py\n+++ b/g.py\n@@ -1 +1 @@\n-x\n+y\n",
     "tests": {"passed": False, "tests_passed": 1, "tests_failed": 2,
               "output": "FAILED", "error": None},
     "cost": 0.01},
]


class TestStartingPatch:
    def test_round1_is_always_none(self):
        for policy in POLICIES:
            assert starting_patch_for_round(policy, []) is None

    def test_iterate_single_entry_returns_normalized(self):
        """Single-entry history returns that patch normalized (rstrip + '\n')."""
        result = starting_patch_for_round("iterate", H)
        expected = H[0]["patch"].rstrip("\n") + "\n"
        assert result == expected
        result_ad = starting_patch_for_round("agent-decides", H)
        assert result_ad == expected

    def test_restarts_return_none(self):
        assert starting_patch_for_round("restart-fresh", H) is None
        assert starting_patch_for_round("restart-informed", H) is None

    def test_unknown_policy_raises(self):
        with pytest.raises(ValueError):
            starting_patch_for_round("yolo", H)

    def test_iterate_with_two_rounds_returns_concat(self):
        """iterate with 2-entry history returns concat of both patches, NOT just r2."""
        result = starting_patch_for_round("iterate", H2)
        r1 = H2[0]["patch"].rstrip("\n")
        r2 = H2[1]["patch"].rstrip("\n")
        expected = r1 + "\n" + r2 + "\n"
        assert result == expected
        # Must NOT be just the last patch
        assert result != H2[1]["patch"]

    def test_agent_decides_with_two_rounds_returns_concat(self):
        """agent-decides with 2-entry history returns concat of both patches."""
        result = starting_patch_for_round("agent-decides", H2)
        r1 = H2[0]["patch"].rstrip("\n")
        r2 = H2[1]["patch"].rstrip("\n")
        expected = r1 + "\n" + r2 + "\n"
        assert result == expected

    def test_iterate_single_round_equals_that_patch(self):
        """Single-round history: result equals that round's patch normalized."""
        single = [H2[0]]
        result = starting_patch_for_round("iterate", single)
        expected = H2[0]["patch"].rstrip("\n") + "\n"
        assert result == expected


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
