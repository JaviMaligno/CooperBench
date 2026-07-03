"""Tests for the trivial-conflict LLM resolver (pure pieces)."""

from cooperbench.eval.resolver import (
    build_resolver_prompt,
    has_conflict_markers,
    parse_resolver_response,
)


CONFLICTED = """import json
<<<<<<< HEAD
from x import A
=======
from x import B
>>>>>>> agent1
print("hi")
"""


class TestHasConflictMarkers:
    def test_detects_markers(self):
        assert has_conflict_markers(CONFLICTED)

    def test_clean_file(self):
        assert not has_conflict_markers("import json\nfrom x import A, B\n")

    def test_marker_like_but_not_at_line_start(self):
        assert not has_conflict_markers("s = 'a <<<<<<< b'\n")


class TestBuildResolverPrompt:
    def test_includes_content_and_giveup_instruction(self):
        prompt = build_resolver_prompt("dirty_equals/__init__.py", CONFLICTED)
        assert "dirty_equals/__init__.py" in prompt
        assert CONFLICTED in prompt
        assert "GIVEUP" in prompt


class TestParseResolverResponse:
    def test_giveup_returns_none(self):
        assert parse_resolver_response("GIVEUP") is None

    def test_giveup_with_explanation_returns_none(self):
        assert parse_resolver_response("GIVEUP\nThe changes are semantically incompatible.") is None

    def test_plain_content_passthrough(self):
        out = parse_resolver_response("import json\nfrom x import A, B\n")
        assert out == "import json\nfrom x import A, B\n"

    def test_strips_code_fences(self):
        out = parse_resolver_response("```python\nimport json\nfrom x import A, B\n```")
        assert out == "import json\nfrom x import A, B\n"

    def test_strips_plain_fences(self):
        out = parse_resolver_response("```\ncode here\n```\n")
        assert out == "code here\n"

    def test_leftover_markers_returns_none(self):
        # A "resolution" that still contains conflict markers is not a resolution.
        assert parse_resolver_response(CONFLICTED) is None

    def test_empty_response_returns_none(self):
        assert parse_resolver_response("") is None
        assert parse_resolver_response("   \n") is None
