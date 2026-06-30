"""Unit tests for C2 territory enforcement helpers (pure, no Docker)."""

from cooperbench.agents._coop.territory import (
    ClaimLedger,
    LineClaimLedger,
    diff_hunk_ranges,
    files_in_patch,
    territory_violations,
)


class TestFilesInPatch:
    def test_extracts_paths_from_diff_headers(self):
        patch = (
            "diff --git a/src/click/core.py b/src/click/core.py\n"
            "--- a/src/click/core.py\n"
            "+++ b/src/click/core.py\n"
            "@@ -1 +1 @@\n-x\n+y\n"
            "diff --git a/src/click/utils.py b/src/click/utils.py\n"
            "--- a/src/click/utils.py\n"
            "+++ b/src/click/utils.py\n"
            "@@ -1 +1 @@\n-a\n+b\n"
        )
        assert files_in_patch(patch) == {"src/click/core.py", "src/click/utils.py"}

    def test_empty_patch_touches_nothing(self):
        assert files_in_patch("") == set()


class TestTerritoryViolations:
    def test_no_violation_when_all_files_owned(self):
        patch = (
            "diff --git a/src/click/core.py b/src/click/core.py\n"
            "--- a/src/click/core.py\n+++ b/src/click/core.py\n@@ -1 +1 @@\n-x\n+y\n"
        )
        assert territory_violations(patch, owned_paths={"src/click/core.py"}) == []

    def test_reports_files_outside_territory(self):
        patch = (
            "diff --git a/src/click/core.py b/src/click/core.py\n"
            "--- a/src/click/core.py\n+++ b/src/click/core.py\n@@ -1 +1 @@\n-x\n+y\n"
            "diff --git a/src/click/utils.py b/src/click/utils.py\n"
            "--- a/src/click/utils.py\n+++ b/src/click/utils.py\n@@ -1 +1 @@\n-a\n+b\n"
        )
        assert territory_violations(patch, owned_paths={"src/click/core.py"}) == ["src/click/utils.py"]


class TestClaimLedger:
    """First-touch file ownership shared across coop agent threads."""

    def test_first_claim_wins_and_no_self_violation(self):
        led = ClaimLedger()
        assert led.claim("agent_a", ["core.py"]) == []
        assert led.owner("core.py") == "agent_a"
        # re-claiming a file you already own is not a violation
        assert led.claim("agent_a", ["core.py"]) == []

    def test_other_agents_file_is_a_violation_but_free_files_claimed(self):
        led = ClaimLedger()
        led.claim("agent_a", ["core.py"])
        # agent_b touches core.py (owned by a) and utils.py (free)
        assert led.claim("agent_b", ["core.py", "utils.py"]) == ["core.py"]
        assert led.owner("utils.py") == "agent_b"  # free file got claimed
        assert led.owner("core.py") == "agent_a"  # ownership unchanged

    def test_violations_are_sorted_and_deduped(self):
        led = ClaimLedger()
        led.claim("agent_a", ["b.py", "a.py"])
        assert led.claim("agent_b", ["b.py", "a.py", "b.py"]) == ["a.py", "b.py"]


class TestDiffHunkRanges:
    """Parse a unified diff into per-file base-line intervals [start, start+count)."""

    def test_extracts_base_intervals_per_file(self):
        diff = (
            "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
            "@@ -10,3 +10,4 @@\n ctx\n-old\n+new1\n+new2\n ctx\n"
            "@@ -50,2 +51,2 @@\n-x\n+y\n z\n"
        )
        assert diff_hunk_ranges(diff) == {"f.py": [(10, 13), (50, 52)]}

    def test_pure_insertion_claims_anchor_line(self):
        # @@ -10,0 +11,2 @@  -> base count 0 -> conservative anchor [10, 11)
        diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -10,0 +11,2 @@\n+a\n+b\n"
        assert diff_hunk_ranges(diff) == {"f.py": [(10, 11)]}


class TestLineClaimLedger:
    """First-touch line-range ownership: same file OK if disjoint, overlap violates."""

    def test_disjoint_ranges_in_same_file_are_allowed(self):
        led = LineClaimLedger()
        assert led.claim("a", "f.py", [(10, 20)]) == []
        assert led.claim("b", "f.py", [(30, 40)]) == []  # disjoint -> fine

    def test_overlapping_range_violates(self):
        led = LineClaimLedger()
        led.claim("a", "f.py", [(10, 20)])
        assert led.claim("b", "f.py", [(15, 18)]) == [(15, 18)]

    def test_same_file_different_agents_no_conflict_across_files(self):
        led = LineClaimLedger()
        led.claim("a", "f.py", [(10, 20)])
        assert led.claim("b", "g.py", [(10, 20)]) == []  # different file
