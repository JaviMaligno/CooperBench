"""LLM-based trivial-conflict resolver for coop merges.

The CooperBench paper (§2.2) resolves trivial merge conflicts with a small
coding model when standard merging fails; the OSS eval release omits that
step, so conflicted pairs die at the merge stage. This module restores a
fair equivalent: a fixed resolver model is asked to resolve a conflicted
file ONLY when the two sides are mechanically compatible (union of imports,
adjacent independent additions); anything requiring feature-level reasoning
must be answered with GIVEUP, and the pair fails as before.

The resolver model is fixed across experiment tiers (it is part of the
eval harness, not of the agents under test).
"""

import os
import re

_MARKER_RE = re.compile(r"^(<<<<<<<|=======|>>>>>>>)", re.M)

RESOLVER_MODEL = os.getenv("COOPERBENCH_RESOLVER_MODEL", "azure/gpt-5.4-mini")


def has_conflict_markers(text: str) -> bool:
    """True if text contains git conflict markers at line starts."""
    return bool(_MARKER_RE.search(text))


def build_resolver_prompt(path: str, content: str) -> str:
    return f"""You are a merge-conflict resolver. Below is the file `{path}` after a failed
git merge, containing conflict markers (<<<<<<< / ======= / >>>>>>>).

Resolve the conflicts ONLY if they are trivial: the two sides are independent
changes that can both be kept mechanically (e.g. each side adds a different
name to the same import line, each side inserts a different function/class
near the same location, each side adds a different parameter to a signature
without interacting logic). In that case output the complete resolved file
content, nothing else (no code fences, no commentary).

If ANY conflict in the file requires understanding the intent of either
change to reconcile them (same logic modified in incompatible ways,
restructured control flow, one side refactors what the other side edits),
output exactly the single word: GIVEUP

File content:
{content}"""


def parse_resolver_response(response: str) -> str | None:
    """Extract resolved file content; None means give up.

    Returns None for GIVEUP answers, empty output, or "resolutions" that
    still contain conflict markers.
    """
    text = response.strip()
    if not text or text.startswith("GIVEUP"):
        return None
    # Strip a single wrapping code fence if present.
    fence = re.match(r"^```[a-zA-Z0-9_+-]*\n(.*)\n?```\s*$", text, re.S)
    if fence:
        text = fence.group(1)
        if not text.endswith("\n"):
            text += "\n"
        if not text.strip():
            return None
    if has_conflict_markers(text):
        return None
    if not text.endswith("\n"):
        text += "\n"
    return text


def resolve_file(path: str, content: str, model: str = RESOLVER_MODEL) -> str | None:
    """Ask the resolver model to resolve one conflicted file.

    Returns resolved content, or None if the model gives up / errors.
    """
    import litellm

    try:
        resp = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": build_resolver_prompt(path, content)}],
            timeout=120,
        )
        return parse_resolver_response(resp.choices[0].message.content or "")
    except Exception:
        return None
