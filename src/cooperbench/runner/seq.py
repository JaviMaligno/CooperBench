"""Sequential pipeline execution.

Agent A implements the first feature; agent B then starts from A's committed
code (via ``starting_patch``) and implements the second feature, so B's patch
stacks on top of A's. The two patches are evaluated by composing base + A + B
(see ``cooperbench.eval.sandbox.test_sequential``). No Redis / messaging / git
server is involved — coordination is structural (B literally builds on A).
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

from cooperbench.eval.sandbox import compose_filtered_patches
from cooperbench.runner.coop import _spawn_agent
from cooperbench.runner.tasks import DEFAULT_DATASET_DIR, DEFAULT_LOGS_DIR
from cooperbench.utils import console


def execute_seq(
    repo_name: str,
    task_id: int,
    features: list[int],
    run_name: str,
    agent_name: str = "mini_swe_agent_v2",
    model_name: str = "vertex_ai/gemini-3-flash-preview",
    force: bool = False,
    quiet: bool = False,
    backend: str = "docker",
    agent_config: str | None = None,
    dataset_dir: Path | str | None = None,
    logs_dir: Path | str | None = None,
) -> dict | None:
    """Execute a sequential-pipeline task (agent A, then agent B on top of A).

    Args:
        agent_config: Path to agent-specific configuration file (optional)
        dataset_dir: Root of the dataset tree.  Defaults to ``./dataset``.
        logs_dir: Root to write run logs under.  Defaults to ``./logs``.
    """
    run_id = uuid.uuid4().hex[:8]
    start_time = datetime.now()

    logs_root = Path(logs_dir) if logs_dir is not None else DEFAULT_LOGS_DIR
    sorted_features = sorted(features)
    f1, f2 = sorted_features[0], sorted_features[1]
    feature_str = "_".join(f"f{f}" for f in sorted_features)
    log_dir = logs_root / run_name / "seq" / repo_name / str(task_id) / feature_str
    result_file = log_dir / "result.json"

    if result_file.exists() and not force:
        with open(result_file) as f:
            prev_result = json.load(f)
        # Re-run if either stage errored.
        agents_had_error = any(a.get("status") == "Error" for a in prev_result.get("agents", {}).values())
        if not agents_had_error:
            return {"skipped": True, **prev_result}

    def _spawn(agent_id: str, feature_id: int, starting_patch: str | None) -> dict:
        try:
            return _spawn_agent(
                repo_name=repo_name,
                task_id=task_id,
                feature_id=feature_id,
                agent_name=agent_name,
                model_name=model_name,
                agent_id=agent_id,
                agents=[agent_id],  # single agent -> solo config, no messaging
                redis_url=None,
                git_server_url=None,
                git_enabled=False,
                git_network=None,
                messaging_enabled=False,
                quiet=quiet,
                backend=backend,
                agent_config=agent_config,
                run_name=None,  # seq writes its own logs below
                features=features,
                dataset_dir=dataset_dir,
                logs_dir=logs_dir,
                starting_patch=starting_patch,
            )
        except Exception as e:
            return {
                "feature_id": feature_id,
                "agent_id": agent_id,
                "status": "Error",
                "patch": "",
                "cost": 0,
                "steps": 0,
                "messages": [],
                "error": str(e),
            }

    # Stage A: implement f1 from base.
    if not quiet:
        console.print(f"  [dim]agent_a (f{f1})[/dim] starting...")
    result_a = _spawn("agent_a", f1, None)
    patch_a = result_a.get("patch", "")

    # Stage B: implement f2 starting from A's committed code.
    if not quiet:
        console.print(f"  [dim]agent_b (f{f2})[/dim] starting from agent_a's patch...")
    result_b = _spawn("agent_b", f2, patch_a or None)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    total_cost = result_a.get("cost", 0) + result_b.get("cost", 0)
    total_steps = result_a.get("steps", 0) + result_b.get("steps", 0)

    # Save files (patch names mirror coop so eval can locate patch_a/patch_b).
    log_dir.mkdir(parents=True, exist_ok=True)
    for fid, r in ((f1, result_a), (f2, result_b)):
        (log_dir / f"agent{fid}.patch").write_text(r.get("patch", ""))
        with open(log_dir / f"agent{fid}_traj.json", "w") as f:
            json.dump(
                {
                    "repo": repo_name,
                    "task_id": task_id,
                    "feature_id": fid,
                    "agent_id": r.get("agent_id"),
                    "model": model_name,
                    "status": r.get("status"),
                    "cost": r.get("cost"),
                    "steps": r.get("steps"),
                    "messages": r.get("messages", []),
                },
                f,
                indent=2,
                default=str,
            )

    stages = {"agent_a": (f1, result_a), "agent_b": (f2, result_b)}
    result_data = {
        "repo": repo_name,
        "task_id": task_id,
        "features": sorted_features,
        "setting": "seq",
        "run_id": run_id,
        "run_name": run_name,
        "agent_framework": agent_name,
        "model": model_name,
        "started_at": start_time.isoformat(),
        "ended_at": end_time.isoformat(),
        "duration_seconds": duration,
        "agents": {
            agent_id: {
                "feature_id": fid,
                "status": r.get("status"),
                "cost": r.get("cost", 0),
                "steps": r.get("steps", 0),
                "input_tokens": r.get("input_tokens", 0),
                "output_tokens": r.get("output_tokens", 0),
                "cache_read_tokens": r.get("cache_read_tokens", 0),
                "cache_write_tokens": r.get("cache_write_tokens", 0),
                "patch_lines": len(r.get("patch", "").splitlines()),
                "error": r.get("error"),
            }
            for agent_id, (fid, r) in stages.items()
        },
        "total_cost": total_cost,
        "total_steps": total_steps,
        "log_dir": str(log_dir),
    }

    with open(log_dir / "result.json", "w") as f:
        json.dump(result_data, f, indent=2)

    return {
        "results": {"agent_a": result_a, "agent_b": result_b},
        "total_cost": total_cost,
        "total_steps": total_steps,
        "duration": duration,
        "run_id": run_id,
        "log_dir": str(log_dir),
    }


def build_integrator_task(feature1_md: str, feature2_md: str, patch_b: str) -> str:
    """Prompt for the C4 integrator agent.

    Engineer 1's feature is already applied to the repo (via starting_patch);
    Engineer 2 built feature 2 independently — their diff is supplied. The
    integrator must make BOTH features work together and submit one patch.
    """
    return (
        "You are the INTEGRATOR. Two engineers implemented two features independently.\n\n"
        "## Feature 1 (Engineer 1 — ALREADY APPLIED to this repository)\n\n"
        f"{feature1_md}\n\n"
        "## Feature 2 (Engineer 2 — implemented independently, NOT yet applied)\n\n"
        f"{feature2_md}\n\n"
        "## Engineer 2's diff (feature 2, against the original base)\n\n"
        "```diff\n"
        f"{patch_b}\n"
        "```\n\n"
        "## Your task\n\n"
        "Feature 1 is already in the working tree. Integrate Feature 2 on top of it so that "
        "BOTH features work together — apply Engineer 2's changes, resolve any conflicts or "
        "incompatibilities, and reconcile overlapping edits. When done, submit your combined "
        "patch the usual way (the submission must contain both features' changes)."
    )


def build_reviewer_task(feature1_md: str, feature2_md: str) -> str:
    """Prompt for the C3+C4 reviewer agent.

    Both features are ALREADY in the working tree: feature 1 was built first,
    then feature 2 was stacked on top of it (a sequential pipeline). The
    reviewer's job is a final PR review — verify both features work together
    and fix whatever is broken, then submit the corrected combined patch.
    """
    return (
        "You are the REVIEWER on a pull request. Two features were implemented one after "
        "the other: feature 1 first, then feature 2 built directly on top of it. BOTH are "
        "already applied to this working tree.\n\n"
        "## Feature 1 (already applied)\n\n"
        f"{feature1_md}\n\n"
        "## Feature 2 (already applied, on top of feature 1)\n\n"
        f"{feature2_md}\n\n"
        "## Your task\n\n"
        "Review the current working tree as a whole. Both features are present; your job is "
        "to make sure they actually work TOGETHER and each is correctly and completely "
        "implemented — fix any bug, regression, or incompatibility you find (feature 2 may "
        "have subtly broken feature 1, or either may be incomplete). When done, submit the "
        "corrected patch the usual way (it must contain both features' changes)."
    )


def execute_c3c4(
    repo_name: str,
    task_id: int,
    features: list[int],
    run_name: str,
    agent_name: str = "mini_swe_agent_v2",
    model_name: str = "vertex_ai/gemini-3-flash-preview",
    force: bool = False,
    quiet: bool = False,
    backend: str = "docker",
    agent_config: str | None = None,
    dataset_dir: Path | str | None = None,
    logs_dir: Path | str | None = None,
) -> dict | None:
    """Execute a C3+C4 combo: sequential pipeline, then a final reviewer.

    Stage 1 (C3): agent A implements feature1; agent B starts from A's committed
    code and stacks feature2 -> the tree is already integrated (base+A+B).
    Stage 2 (C4): a reviewer starts from that sequenced tree, is asked to verify
    both features work together, and submits a corrected patch. Evaluated as
    base + patch_a + patch_b + reviewer.patch against both suites.
    """
    run_id = uuid.uuid4().hex[:8]
    start_time = datetime.now()

    root = Path(dataset_dir) if dataset_dir is not None else DEFAULT_DATASET_DIR
    logs_root = Path(logs_dir) if logs_dir is not None else DEFAULT_LOGS_DIR
    sorted_features = sorted(features)
    f1, f2 = sorted_features[0], sorted_features[1]
    feature_str = "_".join(f"f{f}" for f in sorted_features)
    log_dir = logs_root / run_name / "c3c4" / repo_name / str(task_id) / feature_str
    result_file = log_dir / "result.json"

    if result_file.exists() and not force:
        with open(result_file) as f:
            prev_result = json.load(f)
        agents_had_error = any(a.get("status") == "Error" for a in prev_result.get("agents", {}).values())
        if not agents_had_error:
            return {"skipped": True, **prev_result}

    def _spawn(agent_id: str, feature_id: int, starting_patch: str | None, task_override: str | None) -> dict:
        try:
            return _spawn_agent(
                repo_name=repo_name,
                task_id=task_id,
                feature_id=feature_id,
                agent_name=agent_name,
                model_name=model_name,
                agent_id=agent_id,
                agents=[agent_id],
                redis_url=None,
                git_server_url=None,
                git_enabled=False,
                git_network=None,
                messaging_enabled=False,
                quiet=quiet,
                backend=backend,
                agent_config=agent_config,
                run_name=None,
                features=features,
                dataset_dir=dataset_dir,
                logs_dir=logs_dir,
                starting_patch=starting_patch,
                task_override=task_override,
            )
        except Exception as e:
            return {
                "feature_id": feature_id,
                "agent_id": agent_id,
                "status": "Error",
                "patch": "",
                "cost": 0,
                "steps": 0,
                "messages": [],
                "error": str(e),
            }

    # Stage 1 (C3): A from base, then B stacked on A's committed work.
    if not quiet:
        console.print(f"  [dim]agent_a (f{f1})[/dim] starting...")
    result_a = _spawn("agent_a", f1, None, None)
    patch_a = result_a.get("patch", "")
    if not quiet:
        console.print(f"  [dim]agent_b (f{f2})[/dim] building on agent_a...")
    result_b = _spawn("agent_b", f2, patch_a or None, None)
    patch_b = result_b.get("patch", "")

    # Stage 2 (C4): reviewer starts from the sequenced A+B tree.
    feature1_md = (root / repo_name / f"task{task_id}" / f"feature{f1}" / "feature.md").read_text()
    feature2_md = (root / repo_name / f"task{task_id}" / f"feature{f2}" / "feature.md").read_text()
    seq_tree = compose_filtered_patches(patch_a, patch_b)
    reviewer_task = build_reviewer_task(feature1_md, feature2_md)
    if not quiet:
        console.print("  [dim]reviewer[/dim] reviewing the sequenced tree...")
    result_rev = _spawn("reviewer", f2, seq_tree or None, reviewer_task)
    reviewer_patch = result_rev.get("patch", "")

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    total_cost = result_a.get("cost", 0) + result_b.get("cost", 0) + result_rev.get("cost", 0)
    total_steps = result_a.get("steps", 0) + result_b.get("steps", 0) + result_rev.get("steps", 0)

    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"agent{f1}.patch").write_text(patch_a)
    (log_dir / f"agent{f2}.patch").write_text(patch_b)
    (log_dir / "reviewer.patch").write_text(reviewer_patch)
    for name, r in (("agent_a", result_a), ("agent_b", result_b), ("reviewer", result_rev)):
        with open(log_dir / f"{name}_traj.json", "w") as f:
            json.dump(
                {
                    "repo": repo_name,
                    "task_id": task_id,
                    "agent_id": r.get("agent_id"),
                    "model": model_name,
                    "status": r.get("status"),
                    "cost": r.get("cost"),
                    "steps": r.get("steps"),
                    "messages": r.get("messages", []),
                },
                f,
                indent=2,
                default=str,
            )

    stages = {"agent_a": (f1, result_a), "agent_b": (f2, result_b), "reviewer": (f2, result_rev)}
    result_data = {
        "repo": repo_name,
        "task_id": task_id,
        "features": sorted_features,
        "setting": "c3c4",
        "run_id": run_id,
        "run_name": run_name,
        "agent_framework": agent_name,
        "model": model_name,
        "started_at": start_time.isoformat(),
        "ended_at": end_time.isoformat(),
        "duration_seconds": duration,
        "agents": {
            name: {
                "feature_id": fid,
                "status": r.get("status"),
                "cost": r.get("cost", 0),
                "steps": r.get("steps", 0),
                "patch_lines": len(r.get("patch", "").splitlines()),
                "error": r.get("error"),
            }
            for name, (fid, r) in stages.items()
        },
        "total_cost": total_cost,
        "total_steps": total_steps,
        "log_dir": str(log_dir),
    }
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(result_file, "w") as f:
        json.dump(result_data, f, indent=2, default=str)
    return result_data


def execute_c4(
    repo_name: str,
    task_id: int,
    features: list[int],
    run_name: str,
    agent_name: str = "mini_swe_agent_v2",
    model_name: str = "vertex_ai/gemini-3-flash-preview",
    force: bool = False,
    quiet: bool = False,
    backend: str = "docker",
    agent_config: str | None = None,
    dataset_dir: Path | str | None = None,
    logs_dir: Path | str | None = None,
) -> dict | None:
    """Execute a C4 integrator task.

    Agents A and B implement their features independently from base; a third
    integrator agent then starts from A's committed code, is given B's diff +
    both specs, and reconciles them into one combined patch (evaluated solo-style
    against both feature suites).
    """
    run_id = uuid.uuid4().hex[:8]
    start_time = datetime.now()

    root = Path(dataset_dir) if dataset_dir is not None else DEFAULT_DATASET_DIR
    logs_root = Path(logs_dir) if logs_dir is not None else DEFAULT_LOGS_DIR
    sorted_features = sorted(features)
    f1, f2 = sorted_features[0], sorted_features[1]
    feature_str = "_".join(f"f{f}" for f in sorted_features)
    log_dir = logs_root / run_name / "c4" / repo_name / str(task_id) / feature_str
    result_file = log_dir / "result.json"

    if result_file.exists() and not force:
        with open(result_file) as f:
            prev_result = json.load(f)
        agents_had_error = any(a.get("status") == "Error" for a in prev_result.get("agents", {}).values())
        if not agents_had_error:
            return {"skipped": True, **prev_result}

    def _spawn(agent_id: str, feature_id: int, starting_patch: str | None, task_override: str | None) -> dict:
        try:
            return _spawn_agent(
                repo_name=repo_name,
                task_id=task_id,
                feature_id=feature_id,
                agent_name=agent_name,
                model_name=model_name,
                agent_id=agent_id,
                agents=[agent_id],  # single agent -> solo config, no messaging
                redis_url=None,
                git_server_url=None,
                git_enabled=False,
                git_network=None,
                messaging_enabled=False,
                quiet=quiet,
                backend=backend,
                agent_config=agent_config,
                run_name=None,
                features=features,
                dataset_dir=dataset_dir,
                logs_dir=logs_dir,
                starting_patch=starting_patch,
                task_override=task_override,
            )
        except Exception as e:
            return {
                "feature_id": feature_id,
                "agent_id": agent_id,
                "status": "Error",
                "patch": "",
                "cost": 0,
                "steps": 0,
                "messages": [],
                "error": str(e),
            }

    # Independent development from base.
    if not quiet:
        console.print(f"  [dim]agent_a (f{f1})[/dim] starting...")
    result_a = _spawn("agent_a", f1, None, None)
    patch_a = result_a.get("patch", "")
    if not quiet:
        console.print(f"  [dim]agent_b (f{f2})[/dim] starting...")
    result_b = _spawn("agent_b", f2, None, None)
    patch_b = result_b.get("patch", "")

    # Integrator: start from A's code, reconcile B's diff on top.
    feature1_md = (root / repo_name / f"task{task_id}" / f"feature{f1}" / "feature.md").read_text()
    feature2_md = (root / repo_name / f"task{task_id}" / f"feature{f2}" / "feature.md").read_text()
    integrator_task = build_integrator_task(feature1_md, feature2_md, patch_b)
    if not quiet:
        console.print("  [dim]integrator[/dim] reconciling on top of agent_a's patch...")
    result_int = _spawn("integrator", f2, patch_a or None, integrator_task)
    integrator_patch = result_int.get("patch", "")

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    total_cost = result_a.get("cost", 0) + result_b.get("cost", 0) + result_int.get("cost", 0)
    total_steps = result_a.get("steps", 0) + result_b.get("steps", 0) + result_int.get("steps", 0)

    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"agent{f1}.patch").write_text(patch_a)
    (log_dir / f"agent{f2}.patch").write_text(patch_b)
    (log_dir / "integrator.patch").write_text(integrator_patch)
    for name, r in (("agent_a", result_a), ("agent_b", result_b), ("integrator", result_int)):
        with open(log_dir / f"{name}_traj.json", "w") as f:
            json.dump(
                {
                    "repo": repo_name,
                    "task_id": task_id,
                    "agent_id": r.get("agent_id"),
                    "model": model_name,
                    "status": r.get("status"),
                    "cost": r.get("cost"),
                    "steps": r.get("steps"),
                    "messages": r.get("messages", []),
                },
                f,
                indent=2,
                default=str,
            )

    stages = {"agent_a": (f1, result_a), "agent_b": (f2, result_b), "integrator": (f2, result_int)}
    result_data = {
        "repo": repo_name,
        "task_id": task_id,
        "features": sorted_features,
        "setting": "c4",
        "run_id": run_id,
        "run_name": run_name,
        "agent_framework": agent_name,
        "model": model_name,
        "started_at": start_time.isoformat(),
        "ended_at": end_time.isoformat(),
        "duration_seconds": duration,
        "agents": {
            name: {
                "feature_id": fid,
                "status": r.get("status"),
                "cost": r.get("cost", 0),
                "steps": r.get("steps", 0),
                "patch_lines": len(r.get("patch", "").splitlines()),
                "error": r.get("error"),
            }
            for name, (fid, r) in stages.items()
        },
        "total_cost": total_cost,
        "total_steps": total_steps,
        "log_dir": str(log_dir),
    }
    with open(log_dir / "result.json", "w") as f:
        json.dump(result_data, f, indent=2)

    return {
        "results": {"agent_a": result_a, "agent_b": result_b, "integrator": result_int},
        "total_cost": total_cost,
        "total_steps": total_steps,
        "duration": duration,
        "run_id": run_id,
        "log_dir": str(log_dir),
    }
