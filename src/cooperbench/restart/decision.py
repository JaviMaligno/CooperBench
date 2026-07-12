"""Parse and apply the agent's between-round restart decision."""

import json
import re

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)
_SCOPES = ("file", "directory", "all")


def strip_paths_from_patch(patch: str, scope: str, path: str | None) -> str:
    if scope == "all":
        return ""
    sections = re.split(r"(?=^diff --git )", patch, flags=re.M)
    kept = []
    for section in sections:
        if not section.strip():
            continue
        match = re.match(r"diff --git a/(\S+) b/", section)
        file_path = match.group(1) if match else ""
        drop = (scope == "file" and file_path == path) or (
            scope == "directory"
            and (file_path == path or file_path.startswith((path or "").rstrip("/") + "/"))
        )
        if not drop:
            kept.append(section)
    out = "".join(kept)
    if out and not out.endswith("\n"):
        out += "\n"
    return out


def parse_decision(text: str) -> dict:
    raw = text.strip()
    match = _FENCE.search(raw)
    if match:
        raw = match.group(1)
    try:
        decision = json.loads(raw)
        action = decision.get("action")
        if action == "continue":
            return {"action": "continue"}
        if action == "restart" and decision.get("scope") in _SCOPES:
            return {"action": "restart", "scope": decision["scope"],
                    "path": decision.get("path")}
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    return {"action": "continue", "parse_error": True}


def build_decision_prompt(feedback: str, touched_files: list[str]) -> str:
    files = "\n".join(f"- {file_path}" for file_path in touched_files) or "- (none)"
    return (
        "You are working on a coding task in rounds. Your last attempt's test "
        f"results:\n\n{feedback}\n\nFiles you have modified so far:\n{files}\n\n"
        "Decide how to proceed. Restarting (discarding part or all of your "
        "work) is a legitimate, cost-free option when an approach looks like "
        "a dead end — not an admission of failure. Reply with ONLY a JSON "
        "object, one of:\n"
        '{"action": "continue"}\n'
        '{"action": "restart", "scope": "file", "path": "<one file above>"}\n'
        '{"action": "restart", "scope": "directory", "path": "<dir prefix>"}\n'
        '{"action": "restart", "scope": "all"}\n'
    )
