from cooperbench.restart.decision import (
    build_decision_prompt, parse_decision, strip_paths_from_patch,
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
        result = parse_decision('```json\n{"action":"restart","scope":"file","path":"pkg/a.py"}\n```')
        assert result == {"action": "restart", "scope": "file", "path": "pkg/a.py"}

    def test_garbage_defaults_to_continue_flagged(self):
        result = parse_decision("hmm let me think")
        assert result["action"] == "continue" and result.get("parse_error") is True

    def test_bad_scope_defaults_to_continue_flagged(self):
        result = parse_decision('{"action":"restart","scope":"universe"}')
        assert result["action"] == "continue" and result.get("parse_error") is True


class TestBuildDecisionPrompt:
    def test_mentions_options_and_state(self):
        prompt = build_decision_prompt("2 passed, 3 failed", ["pkg/a.py"])
        assert "continue" in prompt and "restart" in prompt
        assert "pkg/a.py" in prompt and "2 passed, 3 failed" in prompt
        assert "legitimate" in prompt
