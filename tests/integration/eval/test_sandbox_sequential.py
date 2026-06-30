"""Integration tests for sequential-pipeline eval (test_sequential). Requires Docker.

Run with: pytest tests/integration/eval/test_sandbox_sequential.py --run-docker

NOTE on the oracle: CooperBench tasks are designed so a task's two features
OVERLAP the same file. Two base-relative gold patches therefore cannot be
composed (that is the merge problem). In real `seq` mode patch_b is generated
ON TOP of patch_a (B's container has A committed), so it composes by
construction — but we cannot synthesize such a stacked patch from gold data.
So here we validate the compose -> apply -> per-suite-test MECHANICS of
test_sequential with deterministic inputs; the two-overlapping-features-both-pass
behaviour is validated end-to-end by the seq runner integration test.
"""

from pathlib import Path

import pytest

# Alias the import: pytest would otherwise collect `test_sequential` (a name
# starting with "test_") as a test case in this module.
from cooperbench.eval.sandbox import test_sequential as sandbox_test_sequential


@pytest.mark.docker
class TestTestSequential:
    def test_single_patch_passes_its_own_feature(self):
        """A single gold patch as patch_a (patch_b empty) composes, applies, and
        passes ITS feature's suite via the sequential path."""
        task_dir = Path("dataset/llama_index_task/task17244")
        patch_a = (task_dir / "feature1" / "feature.patch").read_text()

        result = sandbox_test_sequential(
            repo_name="llama_index_task",
            task_id=17244,
            feature1_id=1,
            feature2_id=2,
            patch_a=patch_a,
            patch_b="",
            timeout=600,
            backend="docker",
        )

        assert result["error"] is None, f"Error: {result.get('error')}"
        assert result["setting"] == "seq"
        assert result["feature1"]["passed"] is True

    def test_empty_patches_handled(self):
        """Empty inputs are handled gracefully (no crash, no false pass)."""
        result = sandbox_test_sequential(
            repo_name="llama_index_task",
            task_id=17244,
            feature1_id=1,
            feature2_id=2,
            patch_a="",
            patch_b="",
            timeout=300,
            backend="docker",
        )

        assert result["setting"] == "seq"
        assert result["both_passed"] is False
        assert result["error"] is None
