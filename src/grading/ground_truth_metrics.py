"""Ground truth metrics: file recall/precision, LLM judge for goal equivalence."""
import json
import re
from pathlib import Path

import anthropic

from ..config import get_anthropic_api_key, get_data_dir, get_project_root
from ..logging_utils import log_llm_call


def _extract_plan_files(plan_text: str) -> list[str]:
    """Extract file paths mentioned in plan (paths in backticks, or after 'file'/'edit')."""
    paths = set()
    # Paths in backticks: `src/foo/bar.ts`
    for m in re.finditer(r"`([^`]+\.(?:ts|tsx|js|jsx|py|json|md|yaml|yml|txt|go|rs|rb|java|kt))`", plan_text):
        paths.add(m.group(1).strip())
    # Lines like "Edit src/foo.ts" or "Modify src/auth/login.ts"
    for m in re.finditer(r"(?:edit|modify|change|update|open)\s+[`]?([a-zA-Z0-9_./-]+\.[a-zA-Z0-9]+)[`]?", plan_text, re.I):
        paths.add(m.group(1).strip())
    for m in re.finditer(r"([a-z0-9_/.-]+\.(?:ts|tsx|js|jsx|py|json|md))", plan_text):
        p = m.group(1).strip()
        if "/" in p or p.endswith((".ts", ".tsx", ".js", ".py", ".json")):
            paths.add(p)
    return list(paths)


def compute_file_recall_precision(plan_text: str, ground_truth: dict) -> tuple[float, float]:
    """
    Truth: ground_truth["files_modified"] + ground_truth["files_created"].
    Plan files: extracted from plan.
    Return (recall, precision).
    """
    truth_files = set(ground_truth.get("files_modified", []) + ground_truth.get("files_created", []))
    plan_files = set(_extract_plan_files(plan_text))

    def n(p):
        return p.lstrip("./").replace("//", "/")

    truth_n = {n(p) for p in truth_files}
    plan_n = {n(p) for p in plan_files}
    inter_n = truth_n & plan_n
    recall = len(inter_n) / len(truth_n) if truth_n else 1.0
    precision = len(inter_n) / len(plan_n) if plan_n else 1.0
    return recall, precision


def judge_gt_match(
    task_prompt: str,
    ground_truth: dict,
    plan_text: str,
    diff_summary: str = "",
    commit_message: str = "",
    api_key: str | None = None,
) -> float:
    """
    LLM judge: does plan achieve same goal as ground truth? Grade 1-5. Return normalized 0-1.
    commit_message and diff_summary come from the merge commit (parent_sha == repo_state_commit).
    """
    api_key = api_key or get_anthropic_api_key()
    if not api_key:
        return 0.5
    root = get_project_root()
    path = root / "prompts" / "judge_gt_match.txt"
    if path.exists():
        template = path.read_text(encoding="utf-8")
    else:
        template = "User task: {{task_prompt}}\nGround truth: {{files_modified}}, {{key_additions}}\nAI Plan: {{plan}}\nGrade 1-5: GRADE: <n>"
    content = template.replace("{{task_prompt}}", task_prompt)
    content = content.replace("{{files_modified}}", ", ".join(ground_truth.get("files_modified", [])))
    content = content.replace("{{files_created}}", ", ".join(ground_truth.get("files_created", [])))
    content = content.replace("{{key_additions}}", ", ".join(ground_truth.get("key_additions", [])))
    content = content.replace("{{libraries_added}}", ", ".join(ground_truth.get("libraries_added", [])))
    content = content.replace("{{commit_message}}", (commit_message or "N/A")[:2000])
    content = content.replace("{{diff_summary}}", (diff_summary[:8000] if diff_summary else "N/A"))
    content = content.replace("{{plan}}", plan_text[:6000])
    model = "claude-opus-4-6"
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=256,
            messages=[{"role": "user", "content": content}],
        )
        text = (msg.content[0].text if msg.content else "").strip()
        log_llm_call(
            "judge_gt_match",
            content,
            text,
            model=model,
            max_tokens=256,
        )
        m = re.search(r"GRADE:\s*([1-5])", text, re.I)
        if m:
            g = int(m.group(1))
            return (g - 1) / 4.0
    except Exception as e:
        log_llm_call(
            "judge_gt_match",
            content,
            "",
            model=model,
            max_tokens=256,
            extra={"error": str(e)},
        )
    return 0.5


def _load_commits_by_parent(data_dir: Path | None) -> dict[str, dict]:
    """Load merge_commits.json and return dict keyed by parent_sha."""
    if data_dir is None:
        data_dir = get_data_dir()
    path = data_dir / "merge_commits.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        commits = json.load(f)
    return {c["parent_sha"]: c for c in commits if c.get("parent_sha")}


def compute_ground_truth_metrics(
    task: dict,
    plan_text: str,
    repo_map: str = "",
    data_dir: Path | None = None,
    api_key: str | None = None,
) -> dict:
    """
    Return dict: recall, precision, gt_judge (0-1), and raw values for aggregation.
    If data_dir has merge_commits.json, fetches commit by repo_state_commit (parent_sha)
    and passes commit message + diff into the LLM judge.
    """
    gt = task.get("ground_truth", {})
    recall, precision = compute_file_recall_precision(plan_text, gt)
    commit_message = ""
    diff_summary = ""
    commits_by_parent = _load_commits_by_parent(data_dir)
    repo_state_commit = task.get("repo_state_commit", "")
    if repo_state_commit and repo_state_commit in commits_by_parent:
        c = commits_by_parent[repo_state_commit]
        commit_message = c.get("message", "")
        diff_summary = c.get("diff", "")
    gt_judge = judge_gt_match(
        task.get("prompt", ""),
        gt,
        plan_text,
        diff_summary=diff_summary,
        commit_message=commit_message,
        api_key=api_key,
    )
    return {
        "file_recall": recall,
        "file_precision": precision,
        "gt_judge": gt_judge,
    }
