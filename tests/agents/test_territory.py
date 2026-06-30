"""Unit tests for C2 territory enforcement helpers (pure, no Docker)."""

from cooperbench.agents._coop.territory import files_in_patch, territory_violations


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
