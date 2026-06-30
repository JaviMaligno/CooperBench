"""Container-side runtime helpers shared by all CLI agent adapters.

These do not invoke any specific CLI — they're pure shell/string helpers
that any adapter wrapping a containerized CLI agent can call.
"""

from __future__ import annotations

import json
import shlex
from typing import Any, Protocol

# Filesystem layout inside the task container.  Every CooperBench task
# image clones the target repo at ``/workspace/repo``; we adopt the same
# convention for outputs the adapter needs to harvest.
CONTAINER_REPO_PATH = "/workspace/repo"
CONTAINER_COOP_MSG_PATH = "/tmp/cb-coop-msg.py"
CONTAINER_COOP_SEND_LOG = "/tmp/cb-coop-sent.jsonl"
CONTAINER_SETUP_PATH = "/tmp/cb-setup.sh"
CONTAINER_INSTRUCTION_PATH = "/tmp/cb-instruction.txt"


def rewrite_comm_url_for_container(url: str | None) -> str | None:
    """Make a host-side Redis URL reachable from inside the agent container.

    ``localhost`` and ``127.0.0.1`` point at the container itself, not
    the host where the coop runner started Redis.  Substitute
    ``host.docker.internal``, which resolves to the host gateway when
    the container is started with ``--add-host=host.docker.internal:host-gateway``
    (Linux) or natively on Docker Desktop (macOS/Windows).
    """
    if not url:
        return url
    # Use string substitution rather than urlparse to preserve the
    # ``#run:<id>`` fragment that the MessagingConnector relies on.
    for needle in ("//localhost", "//127.0.0.1"):
        if needle in url:
            return url.replace(needle, "//host.docker.internal", 1)
    return url


def build_git_setup_command(*, agent_id: str, server_url: str) -> str:
    """Shell snippet that configures the in-container repo as a participant
    in the shared git remote.

    Mirrors mini_swe_agent_v2's ``GitConnector.setup`` but emitted as a
    single ``bash -lc``-friendly string so it can be exec'd through the
    same ``env.execute`` channel as everything else.  Idempotent: re-running
    is safe (set-url replaces remote if it already exists; branch checkout
    falls back to checkout if it already exists).
    """
    server = shlex.quote(server_url)
    aid = shlex.quote(agent_id)
    branch = shlex.quote(agent_id)
    return (
        f"cd {shlex.quote(CONTAINER_REPO_PATH)} && "
        f"git config user.email 'agent@cooperbench.local' && "
        f"git config user.name {aid} && "
        f"(git remote add team {server} 2>/dev/null || git remote set-url team {server}) && "
        f"(git checkout -b {branch} 2>/dev/null || git checkout {branch}) && "
        f"git push -u team {branch} --force && "
        "git push team HEAD:refs/heads/main --force 2>/dev/null || true"
    )


def parse_sent_messages_log(text: str) -> list[dict[str, Any]]:
    """Parse the in-container coop send-log into a list of message dicts."""
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


class ContainerEnv(Protocol):
    """Minimal interface every adapter needs from its container.

    Defined as a Protocol (not imported from any specific environment
    module) so unit tests can stub in tiny fakes without instantiating
    Docker, and so adapters don't pin themselves to one environment
    implementation.
    """

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]: ...
    def cleanup(self) -> None: ...


def build_environment(
    image: str,
    *,
    network: str | None = None,
    extra_run_args: list[str] | None = None,
    timeout: int = 7200,
    backend: str = "docker",
) -> ContainerEnv:
    """Spin up a long-lived container for the run on the chosen backend.

    ``backend="docker"`` (default) preserves prior behavior. ``backend="modal"``
    runs the container as a Modal sandbox. ``extra_run_args`` and ``network``
    only apply to the Docker backend (Modal sandboxes can't take docker-run
    flags); they're silently ignored on Modal. Tests monkey-patch this to
    inject a fake env.
    """
    if backend == "modal":
        from cooperbench.agents.mini_swe_agent_v2.environments.modal import ModalEnvironment

        return ModalEnvironment(
            image=image,
            cwd=CONTAINER_REPO_PATH,
            timeout=timeout,
        )

    from cooperbench.agents.mini_swe_agent_v2.environments.docker import DockerEnvironment

    run_args = ["--rm"]
    if extra_run_args:
        run_args.extend(extra_run_args)

    kwargs: dict[str, Any] = {
        "image": image,
        "cwd": CONTAINER_REPO_PATH,
        "timeout": timeout,
        "run_args": run_args,
    }
    if network:
        kwargs["network"] = network
    return DockerEnvironment(**kwargs)


def write_file_in_container(env: ContainerEnv, path: str, content: str) -> dict[str, Any]:
    """Write a file inside the container via a heredoc.

    Uses a sentinel that's unlikely to appear in either instruction text
    or shell scripts.
    """
    sentinel = "COOPERBENCH_HEREDOC_EOF_5e7b"
    cmd = f"cat > {shlex.quote(path)} <<'{sentinel}'\n{content}\n{sentinel}\n"
    return env.execute({"command": cmd})


def read_file_from_container(env: ContainerEnv, path: str) -> str:
    result = env.execute({"command": f"cat {shlex.quote(path)} 2>/dev/null"})
    if result.get("returncode") == 0:
        return result.get("output") or ""
    return ""


def apply_patch_in_container(env: ContainerEnv, patch_content: str) -> dict[str, Any]:
    """Apply a patch inside the container's repo and COMMIT it.

    Used by sequential mode so agent B starts from agent A's committed code:
    once A's patch is committed, B's own ``git diff`` comes out stacked on top
    of A (no later merge needed). Falls back to a 3-way apply when a plain apply
    is rejected. An empty patch is a no-op.

    Returns ``{"status": "applied"|"skipped"|"failed", "output": str}``.
    """
    patch = normalize_patch(patch_content)
    if not patch:
        return {"status": "skipped", "output": ""}

    write_file_in_container(env, "/tmp/starting.patch", patch)
    cmd = (
        "cd /workspace/repo && "
        'git config user.email "seq@cooperbench.local" && '
        'git config user.name "CooperBench Seq" && '
        "if git apply /tmp/starting.patch 2>&1; then APPLIED=1; "
        "elif git apply --3way /tmp/starting.patch 2>&1; then APPLIED=1; "
        "else APPLIED=0; fi && "
        'if [ "$APPLIED" = 1 ]; then '
        "  git add -A && git commit -q -m 'Agent A changes' && echo SEQ_APPLIED; "
        "else echo SEQ_FAILED; fi"
    )
    result = env.execute({"command": cmd})
    output = result.get("output") or ""
    return {"status": "applied" if "SEQ_APPLIED" in output else "failed", "output": output}


def normalize_patch(text: str) -> str:
    """Trim leading/trailing blank lines and guarantee exactly one trailing newline.

    ``git apply`` rejects diffs without a terminal newline ("corrupt patch at
    line N").  Adapters that pull the patch out of the container should run it
    through this helper before returning it in ``AgentResult.patch``.

    Importantly, do NOT use ``str.strip()`` — blank context lines inside a
    unified diff are encoded as ``" \\n"`` (a single space + newline), and
    ``strip()`` would eat a trailing one along with the terminator, leaving a
    hunk whose header line counts no longer match its body and which ``git
    apply`` rejects.
    """
    if not text or not text.strip():
        return ""
    return text.lstrip("\n").rstrip("\n") + "\n"
