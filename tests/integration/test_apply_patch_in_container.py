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


@pytest.mark.docker
def test_applies_patch_with_wrong_hunk_count():
    """Patch with a miscounted hunk header is accepted via --recount fallback.

    The hunk header claims ``@@ -1,3 +1,5 @@`` (3 old-side lines) but the
    old file only has 1 line.  Plain ``git apply`` rejects this with exit 128
    ("corrupt patch at line N"); ``git apply --recount`` rebuilds the counts
    from the body and accepts it, adding the two new lines correctly.  This
    mirrors the class of malformed patches agent LLMs emit that the eval
    tolerates in sandbox.py via ``--recount``.
    """
    image = get_image_name("llama_index_task", 17244)
    env = build_environment(image, backend="docker", timeout=300)
    try:
        # Create a one-line file and commit it as starting state.
        setup = (
            "cd /workspace/repo && "
            "git config user.email 'test@cooperbench.local' && "
            "git config user.name 'Test' && "
            "echo 'hello' > hello.txt && "
            "git add hello.txt && "
            "git commit -q -m 'add hello.txt'"
        )
        env.execute({"command": setup})

        # Hunk header claims old side has 3 lines (-1,3) but the file only has
        # 1 line — plain `git apply` exits 128 ("corrupt patch"); --recount
        # ignores the header counts, rebuilds them from the body, and succeeds.
        bad_patch = (
            "diff --git a/hello.txt b/hello.txt\n"
            "index ce01362..f9c4e8c 100644\n"
            "--- a/hello.txt\n"
            "+++ b/hello.txt\n"
            "@@ -1,3 +1,5 @@\n"  # wrong: old side claims 3 lines; file has 1
            " hello\n"
            "+world\n"
            "+foo\n"
        )

        result = apply_patch_in_container(env, bad_patch)
        assert result["status"] == "applied", (
            f"Expected 'applied' but got {result['status']!r}. Output:\n{result['output']}"
        )

        # The file content must reflect both added lines.
        content = env.execute({"command": "cat /workspace/repo/hello.txt"})["output"]
        assert "world" in content, f"Missing 'world' in:\n{content}"
        assert "foo" in content, f"Missing 'foo' in:\n{content}"
    finally:
        env.cleanup()
