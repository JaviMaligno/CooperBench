"""Territory helpers for C2 (enforced file ownership).

In the enforced-ownership condition each agent is assigned a set of files it
may modify; edits outside that territory are rejected. These pure helpers
inspect a unified diff and report which files it touches and which fall outside
a given ownership set. Kept dependency-free so they unit-test without Docker.
"""

import re

_DIFF_GIT = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.M)


def files_in_patch(patch_text: str) -> set[str]:
    """Repo-relative paths a unified diff modifies (the ``b/`` side)."""
    if not patch_text:
        return set()
    return {m.group(2) for m in _DIFF_GIT.finditer(patch_text)}


def territory_violations(patch_text: str, owned_paths) -> list[str]:
    """Sorted list of files the patch touches that are NOT in ``owned_paths``."""
    owned = set(owned_paths)
    return sorted(f for f in files_in_patch(patch_text) if f not in owned)
