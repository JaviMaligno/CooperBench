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

from cooperbench.runner.coop import _spawn_agent
from cooperbench.runner.tasks import DEFAULT_LOGS_DIR
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
