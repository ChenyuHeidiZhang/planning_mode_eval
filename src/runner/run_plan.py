"""Run headless Claude Plan Mode for each task and capture plan output."""
import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..config import load_config, get_data_dir, get_anthropic_api_key, get_claude_working_dir
from ..contextizer.clone import get_repo_path


def _extract_plan_path_from_text(text: str) -> Path | None:
    """Extract path to actual plan file from assistant text (e.g. `/abs/path/plan.md`)."""
    if not text or not text.strip():
        return None
    # Backtick-quoted path ending in .md
    match = re.search(r"`([^`]+\.md)`", text)
    if match:
        p = Path(match.group(1).strip())
        if p.exists():
            return p
    return None


def _format_message_for_raw(message) -> str:
    """Format a single SDK message for plan_raw.txt."""
    cls = type(message).__name__
    if hasattr(message, "content"):
        parts = []
        for block in message.content:
            bcls = type(block).__name__
            if hasattr(block, "text"):
                parts.append(f"[{bcls}]\n{block.text}")
            else:
                parts.append(f"[{bcls}]\n{block!r}")
        return f"--- {cls} ---\n" + "\n".join(parts)
    return f"--- {cls} ---\n{message!r}"


def _extract_plan_text_from_messages(messages: list) -> str:
    """Extract plan markdown from assistant text in messages (last AssistantMessage)."""
    try:
        from claude_agent_sdk import AssistantMessage, TextBlock
    except ImportError:
        from claude_agent_sdk import AssistantMessage
        from claude_agent_sdk.types import TextBlock  # type: ignore[attr-defined]

    plan_parts = []
    for msg in reversed(messages):
        if isinstance(msg, AssistantMessage) and hasattr(msg, "content"):
            for block in msg.content:
                if isinstance(block, TextBlock) and getattr(block, "text", None):
                    plan_parts.append(block.text)
            if plan_parts:
                break
    return "\n\n".join(reversed(plan_parts)) if plan_parts else ""


async def _collect_messages(prompt: str, options):
    """Consume query iterator into a list."""
    from claude_agent_sdk import query

    messages = []
    async for message in query(prompt=prompt, options=options):
        messages.append(message)
        # print(message)
    return messages


async def _run_plan_async(
    prompt: str,
    repo_path: Path,
    out_dir: Path,
    task_id: str,
    timeout_seconds: int,
    env: dict,
) -> Path:
    """Run plan mode via Agent SDK; save raw messages and plan. Returns plan_dest or plan_raw path."""
    from claude_agent_sdk import ClaudeAgentOptions

    claude_plans_dir = get_claude_working_dir() / "plans" / task_id
    claude_plans_dir.mkdir(parents=True, exist_ok=True)
    claude_plan_path = claude_plans_dir / "plan.md"
    plan_save_instruction = (
        f"Save your final plan as a single markdown file at this path: {claude_plan_path.resolve()}"
    )
    prompt_with_instruction = prompt.strip() + plan_save_instruction

    options = ClaudeAgentOptions(
        permission_mode="plan",
        cwd=str(repo_path),
        env=env,
    )
    messages = []
    try:
        messages = await asyncio.wait_for(
            _collect_messages(prompt_with_instruction, options),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        (out_dir / "error.txt").write_text("Plan run timed out.", encoding="utf-8")
        raw_lines = [_format_message_for_raw(m) for m in messages]
        (out_dir / "plan_raw.txt").write_text("\n\n".join(raw_lines), encoding="utf-8")
        return out_dir / "plan_raw.txt"

    raw_lines = [_format_message_for_raw(m) for m in messages]
    (out_dir / "plan_raw.txt").write_text("\n\n".join(raw_lines), encoding="utf-8")

    plan_dest = out_dir / "plan.md"
    if claude_plan_path.exists():
        shutil.copy2(claude_plan_path, plan_dest)
        return plan_dest

    plan_text = _extract_plan_text_from_messages(messages)
    embedded_plan = _extract_plan_path_from_text(plan_text)
    if embedded_plan is not None:
        print(f"Embedded plan found at {embedded_plan}")
        shutil.copy2(embedded_plan, plan_dest)
        return plan_dest
    return out_dir / "plan_raw.txt"


def run_plan_for_task(
    task: dict,
    repo_url: str,
    plans_dir: Path | None = None,
    timeout_seconds: int | None = None,
) -> Path:
    """
    Checkout repo_state_commit, run Claude Agent SDK in plan mode (no CLI), save plan.
    Uses ANTHROPIC_API_KEY from env. Returns path to saved plan.md or plan_raw.txt.
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
    timeout = timeout_seconds or cfg.get("plan_timeout_seconds", 300)
    prompt = task.get("prompt", "")
    env = os.environ.copy()
    api_key = get_anthropic_api_key()
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key

    return asyncio.run(
        _run_plan_async(
            prompt=prompt,
            repo_path=repo_path,
            out_dir=out_dir,
            task_id=task_id,
            timeout_seconds=timeout,
            env=env,
        )
    )


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
        print(f"Ran plan for task {task.get('task_id', 'unknown')}")
    return results
