"""Unit tests for C2 territory enforcement helpers (pure, no Docker)."""

from cooperbench.agents._coop.territory import ClaimLedger, files_in_patch, territory_violations


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
