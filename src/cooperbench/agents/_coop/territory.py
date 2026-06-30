"""Territory helpers for C2 (enforced file ownership).

In the enforced-ownership condition each agent is assigned a set of files it
may modify; edits outside that territory are rejected. These pure helpers
inspect a unified diff and report which files it touches and which fall outside
a given ownership set. Kept dependency-free so they unit-test without Docker.
"""

import re
import threading

_DIFF_GIT = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.M)
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+")


def diff_hunk_ranges(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """Per-file base-line intervals ``[start, start+count)`` a diff touches.

    Reads each file section's hunk headers ``@@ -a,b +c,d @@``; the base side
    ``-a,b`` covers lines ``[a, a+b)``. A pure insertion (``b == 0``)
    conservatively claims its anchor line ``[a, a+1)``. Line numbers are in the
    base file, so two agents' intervals on the same file are comparable.
    """
    result: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        m = _DIFF_GIT.match(line)
        if m:
            current = m.group(2)
            result.setdefault(current, [])
            continue
        h = _HUNK_HEADER.match(line)
        if h and current is not None:
            start = int(h.group(1))
            count = int(h.group(2)) if h.group(2) is not None else 1
            end = start + count if count > 0 else start + 1
            result[current].append((start, end))
    return result


class LineClaimLedger:
    """First-touch line-range ownership across the coop agent threads.

    Lets two agents edit the same file in disjoint base-line regions; an edit
    overlapping a region another agent already owns is a violation. Finer than
    :class:`ClaimLedger` (whole-file), which blocks any shared-file edit.
    """

    def __init__(self) -> None:
        self._owned: dict[str, list[tuple[int, int, str]]] = {}
        self._lock = threading.Lock()

    def claim(self, agent_id: str, file: str, intervals) -> list[tuple[int, int]]:
        """Claim base-line intervals in ``file`` for ``agent_id`` (first-touch).

        Returns the requested intervals that overlap a region already owned by
        ANOTHER agent (the violations); non-overlapping intervals are claimed.
        """
        violations: list[tuple[int, int]] = []
        with self._lock:
            owned = self._owned.setdefault(file, [])
            for start, end in intervals:
                conflict = any(
                    other_agent != agent_id and start < other_end and other_start < end
                    for other_start, other_end, other_agent in owned
                )
                if conflict:
                    violations.append((start, end))
                else:
                    owned.append((start, end, agent_id))
        return violations


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
