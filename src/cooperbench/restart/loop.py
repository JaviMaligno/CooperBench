"""Run attempt, evaluation, feedback, and policy transitions for one feature."""

import json
from datetime import datetime
from pathlib import Path

from cooperbench.agents._coop.territory import files_in_patch
from cooperbench.restart.decision import build_decision_prompt, parse_decision, strip_paths_from_patch
from cooperbench.restart.feedback import format_feedback
from cooperbench.restart.policies import build_round_task, starting_patch_for_round
from cooperbench.runner.tasks import DEFAULT_DATASET_DIR, DEFAULT_LOGS_DIR


def _real_spawn(**kwargs):
    from cooperbench.runner.coop import _spawn_agent
    return _spawn_agent(**kwargs)


def _real_eval(repo, task_id, feature_id, patch, backend="docker", dataset_dir=None):
    from cooperbench.eval.sandbox import run_patch_test
    return run_patch_test(repo, task_id, feature_id, agent_patch=patch or None,
                          backend=backend, dataset_dir=dataset_dir)


def _real_decide(model_name):
    def decide(feedback: str, touched: list[str]) -> dict:
        import litellm
        try:
            response = litellm.completion(
                model=model_name,
                messages=[{"role": "user", "content": build_decision_prompt(feedback, touched)}],
                timeout=120,
            )
            return parse_decision(response.choices[0].message.content or "")
        except Exception as exc:
            return {"action": "continue", "parse_error": True, "error": str(exc)[:200]}
    return decide


def execute_restart_loop(
    repo: str, task_id: int, feature_id: int, policy: str, run_name: str,
    model_name: str, rounds: int = 4, backend: str = "docker",
    dataset_dir: Path | str | None = None, logs_dir: Path | str | None = None,
    force: bool = False, quiet: bool = True, spawn_fn=None, eval_fn=None,
    decide_fn=None,
) -> dict:
    root = Path(dataset_dir) if dataset_dir is not None else DEFAULT_DATASET_DIR
    logs_root = Path(logs_dir) if logs_dir is not None else DEFAULT_LOGS_DIR
    log_dir = logs_root / run_name / "restart" / repo / str(task_id) / f"f{feature_id}"
    result_file = log_dir / "result.json"
    if result_file.exists() and not force:
        return {"skipped": True, **json.loads(result_file.read_text())}

    spawn_fn = spawn_fn or _real_spawn
    eval_fn = eval_fn or _real_eval
    if policy == "agent-decides" and decide_fn is None:
        decide_fn = _real_decide(model_name)

    base_task = (root / repo / f"task{task_id}" / f"feature{feature_id}" / "feature.md").read_text()
    log_dir.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    for round_idx in range(1, rounds + 1):
        round_dir = log_dir / f"round_{round_idx}"
        if (round_dir / "tests.json").exists() and (round_dir / "attempt.patch").exists():
            agent_path = round_dir / "agent.json"
            agent_data = json.loads(agent_path.read_text()) if agent_path.exists() else {}
            history.append({
                "round": round_idx,
                "patch": (round_dir / "attempt.patch").read_text(),
                "tests": json.loads((round_dir / "tests.json").read_text()),
                "cost": agent_data.get("cost", 0),
            })
        else:
            break

    solved = any(item["tests"].get("passed") for item in history)
    start = datetime.now()
    while not solved and len(history) < rounds:
        round_idx = len(history) + 1
        round_dir = log_dir / f"round_{round_idx}"
        round_dir.mkdir(parents=True, exist_ok=True)
        starting_patch = starting_patch_for_round(policy, history)
        task = build_round_task(policy, base_task, history)

        if policy == "agent-decides" and history:
            feedback = format_feedback(history[-1]["tests"], history[-1]["round"])
            touched = sorted(files_in_patch(history[-1]["patch"]))
            decision = decide_fn(feedback, touched)
            (round_dir / "decision.json").write_text(json.dumps(decision, indent=2))
            if decision.get("action") == "restart":
                starting_patch = strip_paths_from_patch(
                    starting_patch or "", decision["scope"], decision.get("path")
                ) or None

        agent = spawn_fn(
            repo_name=repo, task_id=task_id, feature_id=feature_id,
            agent_name="mini_swe_agent_v2", model_name=model_name,
            agent_id="restart_agent", agents=["restart_agent"], redis_url=None,
            git_server_url=None, git_enabled=False, git_network=None,
            messaging_enabled=False, quiet=quiet, backend=backend,
            agent_config=None, run_name=None, features=[feature_id],
            dataset_dir=dataset_dir, logs_dir=logs_dir,
            starting_patch=starting_patch, task_override=task,
        )
        patch = agent.get("patch", "") or ""
        tests = eval_fn(repo, task_id, feature_id, patch,
                        backend=backend, dataset_dir=dataset_dir)
        (round_dir / "attempt.patch").write_text(patch)
        (round_dir / "tests.json").write_text(json.dumps(tests, indent=2))
        (round_dir / "feedback.txt").write_text(format_feedback(tests, round_idx))
        (round_dir / "agent.json").write_text(json.dumps({
            "status": agent.get("status"), "cost": agent.get("cost", 0),
            "steps": agent.get("steps", 0),
        }, indent=2))
        history.append({"round": round_idx, "patch": patch, "tests": tests,
                        "cost": agent.get("cost", 0)})
        solved = bool(tests.get("passed"))

    solve_round = next((item["round"] for item in history
                        if item["tests"].get("passed")), None)
    result = {
        "repo": repo, "task_id": task_id, "feature_id": feature_id,
        "policy": policy, "model": model_name, "rounds_run": len(history),
        "solved": solved, "solve_round": solve_round,
        "total_cost": sum(item["cost"] for item in history),
        "rounds": [{
            "round": item["round"], "passed": item["tests"].get("passed"),
            "tests_passed": item["tests"].get("tests_passed"),
            "tests_failed": item["tests"].get("tests_failed"), "cost": item["cost"],
        } for item in history],
        "started_at": start.isoformat(), "ended_at": datetime.now().isoformat(),
        "log_dir": str(log_dir),
    }
    result_file.write_text(json.dumps(result, indent=2))
    return result
