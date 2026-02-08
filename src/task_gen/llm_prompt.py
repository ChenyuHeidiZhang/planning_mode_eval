"""Use LLM to reverse-engineer a user prompt from a git diff."""
from pathlib import Path

import anthropic

from ..config import load_config, get_anthropic_api_key, get_project_root
from ..logging_utils import log_llm_call
from .ground_truth import GroundTruth as GT

COMMIT_TYPE_FEATURE = "feature_request"
COMMIT_TYPE_BUG = "bug_fix"
COMMIT_TYPE_REFACTOR = "code_refactoring"
COMMIT_TYPE_DO_NOT_USE = "do_not_use"
COMMIT_TYPES = (COMMIT_TYPE_FEATURE, COMMIT_TYPE_BUG, COMMIT_TYPE_REFACTOR)

CLASSIFY_COMMIT_PROMPT = """Classify this git merge commit into exactly one category based on its message.

Categories:
- feature_request: New functionality, new feature, enhancement, or new capability.
- bug_fix: Fixing a bug, correcting incorrect behavior, or fixing a regression.
- code_refactoring: Restructuring code without changing behavior (renames, extracting functions, style cleanup, no new features or bug fixes).
- do_not_use: The commit does not have large enough scope that would require an AI agent to write a plan. Use this for trivial changes, tiny tweaks, config-only updates, dependency bumps, or other changes that do not warrant planning.

Reply with exactly one line:
TYPE: <feature_request | bug_fix | code_refactoring | do_not_use>

Commit message:
{{commit_message}}
"""


def classify_commit_type(
    commit_message: str,
    *,
    api_key: str | None = None,
) -> str:
    """
    Classify a commit as feature_request, bug_fix, or code_refactoring using the LLM.
    Uses only the commit message.
    """
    api_key = api_key or get_anthropic_api_key()
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is required for task generation")
    content = CLASSIFY_COMMIT_PROMPT.replace("{{commit_message}}", commit_message)
    model = "claude-sonnet-4-20250514"
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=64,
        messages=[{"role": "user", "content": content}],
    )
    text = (msg.content[0].text if msg.content else "").strip()
    log_llm_call(
        "classify_commit",
        content,
        text,
        model=model,
        max_tokens=64,
    )
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("TYPE:"):
            raw = line.split(":", 1)[-1].strip().lower().replace(" ", "_")
            if raw in ("feature_request", "bug_fix", "code_refactoring"):
                return raw
            if raw == "do_not_use":
                return COMMIT_TYPE_DO_NOT_USE
            if "feature" in raw or raw == "feature":
                return COMMIT_TYPE_FEATURE
            if "bug" in raw or "fix" in raw:
                return COMMIT_TYPE_BUG
            if "refactor" in raw:
                return COMMIT_TYPE_REFACTOR
    return COMMIT_TYPE_FEATURE


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
    model = "claude-sonnet-4-20250514"
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )
    text = msg.content[0].text if msg.content else ""
    log_llm_call(
        "reverse_engineer_prompt",
        content,
        text,
        model=model,
        max_tokens=1024,
    )
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
    task_type: str | None = None,
) -> dict:
    """Build a TaskObject dict for JSON serialization."""
    gt = ground_truth
    out = {
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
        "task_type": task_type,
    }
    return out
