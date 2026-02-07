"""Ground truth metrics: file recall/precision, LLM judge for goal equivalence."""
import re

import anthropic

from ..config import get_anthropic_api_key, get_project_root


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
    if not truth_files:
        return 1.0, 1.0 if not plan_files else 0.0

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
    api_key: str | None = None,
) -> float:
    """
    LLM judge: does plan achieve same goal as ground truth? Grade 1-5. Return normalized 0-1.
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
    content = content.replace("{{diff_summary}}", diff_summary[:2000] if diff_summary else "N/A")
    content = content.replace("{{plan}}", plan_text[:6000])
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            messages=[{"role": "user", "content": content}],
        )
        text = (msg.content[0].text if msg.content else "").strip()
        m = re.search(r"GRADE:\s*([1-5])", text, re.I)
        if m:
            g = int(m.group(1))
            return (g - 1) / 4.0
    except Exception:
        pass
    return 0.5


def compute_ground_truth_metrics(
    task: dict,
    plan_text: str,
    repo_map: str = "",
    api_key: str | None = None,
) -> dict:
    """
    Return dict: recall, precision, gt_judge (0-1), and raw values for aggregation.
    """
    gt = task.get("ground_truth", {})
    recall, precision = compute_file_recall_precision(plan_text, gt)
    gt_judge = judge_gt_match(
        task.get("prompt", ""),
        gt,
        plan_text,
        api_key=api_key,
    )
    return {
        "file_recall": recall,
        "file_precision": precision,
        "gt_judge": gt_judge,
    }
