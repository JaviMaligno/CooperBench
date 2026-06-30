"""Territory helpers for C2 (enforced file ownership).

In the enforced-ownership condition each agent is assigned a set of files it
may modify; edits outside that territory are rejected. These pure helpers
inspect a unified diff and report which files it touches and which fall outside
a given ownership set. Kept dependency-free so they unit-test without Docker.
"""

import re
import threading

_DIFF_GIT = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.M)


class ClaimLedger:
    """First-touch file ownership shared across the coop agent threads.

    The two coop agents run as threads in one process, so a single shared
    ledger (dict + lock) is enough — no Redis. The first agent to touch a file
    owns it; another agent touching an owned file is a territory violation
    (its edit gets reverted by the enforcement hook).
    """

    def __init__(self) -> None:
        self._owner: dict[str, str] = {}
        self._lock = threading.Lock()

    def claim(self, agent_id: str, files) -> list[str]:
        """Claim each file for ``agent_id`` (first-touch wins).

        Returns the sorted, deduped files already owned by ANOTHER agent.
        """
        violations: set[str] = set()
        with self._lock:
            for f in files:
                current = self._owner.get(f)
                if current is None:
                    self._owner[f] = agent_id
                elif current != agent_id:
                    violations.add(f)
        return sorted(violations)

    def owner(self, path: str) -> str | None:
        return self._owner.get(path)


def files_in_patch(patch_text: str) -> set[str]:
    """Repo-relative paths a unified diff modifies (the ``b/`` side)."""
    if not patch_text:
        return set()
    return {m.group(2) for m in _DIFF_GIT.finditer(patch_text)}


def territory_violations(patch_text: str, owned_paths) -> list[str]:
    """Sorted list of files the patch touches that are NOT in ``owned_paths``."""
    owned = set(owned_paths)
    return sorted(f for f in files_in_patch(patch_text) if f not in owned)
