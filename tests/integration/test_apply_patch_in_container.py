"""Integration test for apply_patch_in_container (sequential mode helper).

Requires Docker. Run with:
    pytest tests/integration/test_apply_patch_in_container.py --run-docker

This is the piece that lets agent B start from agent A's code: apply A's patch
inside B's fresh container and COMMIT it, so B's own `git diff` comes out stacked
on top of A.
"""

from pathlib import Path

import pytest

from cooperbench.agents._coop.runtime import apply_patch_in_container, build_environment
from cooperbench.utils import get_image_name


@pytest.mark.docker
def test_applies_and_commits_starting_patch():
    image = get_image_name("llama_index_task", 17244)
    patch = Path("dataset/llama_index_task/task17244/feature1/feature.patch").read_text()

    env = build_environment(image, backend="docker", timeout=300)
    try:
        base = env.execute({"command": "cd /workspace/repo && git rev-parse HEAD"})["output"].strip()

        status = apply_patch_in_container(env, patch)
        assert status["status"] == "applied", status

        # Committed: HEAD advanced and the working tree is clean (not just applied).
        head = env.execute({"command": "cd /workspace/repo && git rev-parse HEAD"})["output"].strip()
        assert head != base
        porcelain = env.execute({"command": "cd /workspace/repo && git status --porcelain"})["output"].strip()
        assert porcelain == "", f"working tree not clean: {porcelain}"

        # The committed change is real and touches feature1's file.
        names = env.execute(
            {"command": f"cd /workspace/repo && git diff {base} HEAD --name-only"}
        )["output"]
        assert "types.py" in names, names
    finally:
        env.cleanup()


@pytest.mark.docker
def test_empty_patch_is_skipped():
    image = get_image_name("llama_index_task", 17244)
    env = build_environment(image, backend="docker", timeout=300)
    try:
        base = env.execute({"command": "cd /workspace/repo && git rev-parse HEAD"})["output"].strip()
        status = apply_patch_in_container(env, "")
        assert status["status"] == "skipped"
        head = env.execute({"command": "cd /workspace/repo && git rev-parse HEAD"})["output"].strip()
        assert head == base  # nothing committed
    finally:
        env.cleanup()
