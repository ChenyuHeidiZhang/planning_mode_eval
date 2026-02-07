"""Run headless Claude Plan Mode for each task and capture plan output."""
import subprocess
from pathlib import Path

from ..config import load_config, get_data_dir
from ..contextizer.clone import get_repo_path


def run_plan_for_task(
    task: dict,
    repo_url: str,
    plans_dir: Path | None = None,
    claude_path: str | None = None,
    timeout_seconds: int | None = None,
) -> Path:
    """
    Checkout repo_state_commit, run claude --permission-mode plan -p "<prompt>", save plan.
    Returns path to saved plan.md (or plan_raw.txt if plan.md not produced).
    """
    cfg = load_config()
    repo_path = get_repo_path(repo_url)
    if not repo_path.exists():
        raise FileNotFoundError(f"Repo not cloned: {repo_path}")
    data_dir = plans_dir or get_data_dir()
    plans_base = data_dir / "plans"
    task_id = task.get("task_id", "unknown")
    out_dir = plans_base / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    parent_commit = task.get("repo_state_commit")
    if not parent_commit:
        raise ValueError("task must have repo_state_commit")
    subprocess.run(
        ["git", "checkout", "-f", parent_commit],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    claude_cmd = claude_path or cfg.get("claude_cli_path", "claude")
    timeout = timeout_seconds or cfg.get("plan_timeout_seconds", 300)
    prompt = task.get("prompt", "")
    proc = subprocess.run(
        [claude_cmd, "--permission-mode", "plan", "-p", prompt],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    raw_out = proc.stdout or ""
    raw_err = proc.stderr or ""
    (out_dir / "plan_raw.txt").write_text(raw_out, encoding="utf-8")
    if raw_err:
        (out_dir / "plan_stderr.txt").write_text(raw_err, encoding="utf-8")
    plan_md = repo_path / ".claude" / "plan.md"
    if plan_md.exists():
        plan_content = plan_md.read_text(encoding="utf-8")
        plan_dest = out_dir / "plan.md"
        plan_dest.write_text(plan_content, encoding="utf-8")
        return plan_dest
    if raw_out.strip():
        plan_dest = out_dir / "plan.md"
        plan_dest.write_text(raw_out, encoding="utf-8")
        return plan_dest
    return out_dir / "plan_raw.txt"


def run_plans_for_all_tasks(
    tasks: list[dict],
    repo_url: str,
    plans_dir: Path | None = None,
) -> list[tuple[dict, Path]]:
    """Run plan for each task. Returns list of (task, plan_path). Failed runs yield plan_path to plan_raw.txt or missing."""
    results = []
    for task in tasks:
        try:
            path = run_plan_for_task(task, repo_url, plans_dir=plans_dir)
            results.append((task, path))
        except Exception as e:
            data_dir = plans_dir or get_data_dir()
            out_dir = data_dir / "plans" / task.get("task_id", "unknown")
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "error.txt").write_text(str(e), encoding="utf-8")
            results.append((task, out_dir / "plan.md"))  # placeholder; may not exist
    return results
