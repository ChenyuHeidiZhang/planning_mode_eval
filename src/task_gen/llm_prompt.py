"""Use LLM to reverse-engineer a user prompt from a git diff."""
from pathlib import Path

import anthropic

from ..config import load_config, get_anthropic_api_key, get_project_root
from .ground_truth import GroundTruth as GT


def _load_prompt_template() -> str:
    root = get_project_root()
    path = root / "prompts" / "task_gen.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return """Reverse-engineer this git diff. Write the prompt a user would have asked to trigger this change. Do not mention the solution.
Output exactly two lines:
PROMPT: <user prompt>
DIFFICULTY: <Easy | Medium | Hard>

Repo Map (context):
{{repo_map}}

Commit message:
{{commit_message}}

Diff:
{{diff}}
"""


def reverse_engineer_prompt(
    repo_map: str,
    commit_message: str,
    diff: str,
    api_key: str | None = None,
) -> tuple[str, str]:
    """
    Call Anthropic to get user prompt and difficulty from diff + repo map.
    Returns (prompt_str, difficulty).
    """
    api_key = api_key or get_anthropic_api_key()
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is required for task generation")
    cfg = load_config()
    max_chars = cfg.get("repo_map_max_chars", 150000)
    if len(repo_map) > max_chars:
        repo_map = repo_map[:max_chars] + "\n... [truncated]"
    if len(diff) > 100000:
        diff = diff[:100000] + "\n... [truncated]"
    template = _load_prompt_template()
    content = template.replace("{{repo_map}}", repo_map).replace("{{commit_message}}", commit_message).replace("{{diff}}", diff)
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )
    text = msg.content[0].text if msg.content else ""
    prompt_str = ""
    difficulty = "Medium"
    for line in text.splitlines():
        if line.strip().upper().startswith("PROMPT:"):
            prompt_str = line.split(":", 1)[-1].strip()
        elif line.strip().upper().startswith("DIFFICULTY:"):
            d = line.split(":", 1)[-1].strip().capitalize()
            if d in ("Easy", "Medium", "Hard"):
                difficulty = d
    if not prompt_str:
        prompt_str = text.strip() or "Implement the change suggested by the commit."
    return prompt_str, difficulty


def build_task_object(
    task_id: str,
    prompt: str,
    repo_state_commit: str,
    ground_truth: GT,
    difficulty: str = "Medium",
) -> dict:
    """Build a TaskObject dict for JSON serialization."""
    gt = ground_truth
    return {
        "task_id": task_id,
        "prompt": prompt,
        "repo_state_commit": repo_state_commit,
        "ground_truth": {
            "files_modified": gt.files_modified,
            "files_created": gt.files_created,
            "key_additions": gt.key_additions,
            "libraries_added": gt.libraries_added,
        },
        "difficulty": difficulty,
    }
