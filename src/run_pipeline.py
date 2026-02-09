"""
CLI entrypoint: contextize, generate-tasks, run-plans, grade, all.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
import random

from .config import load_config, get_data_dir
from .logging_utils import set_run_log_subdir
from .contextizer import clone_repo
from .contextizer.repomix import get_repo_map_cached
from .task_gen.git_extract import extract_merge_commits
from .task_gen.git_extract import MergeCommitInfo
from .task_gen.ground_truth import extract_ground_truth
from .task_gen.llm_prompt import (
    reverse_engineer_prompt,
    build_task_object,
    classify_commit_type,
    COMMIT_TYPE_FEATURE,
    COMMIT_TYPE_BUG,
    COMMIT_TYPE_REFACTOR,
    COMMIT_TYPE_DO_NOT_USE,
)
from .contextizer.clone import get_repo_path
from .runner.run_plan import run_plans_for_all_tasks
from .grading.claims import extract_claims
from .grading.verify_search import verify_claims_via_search, score_logical_soundness
from .grading.ground_truth_metrics import compute_ground_truth_metrics
from .grading.text_quality import score_text_quality
from .grading.aggregate import aggregate_task_result


def _save_merge_commits(merges: list[MergeCommitInfo], data_dir: Path) -> None:
    """Save merge commits to data_dir/merge_commits.json for later grading lookup."""
    data_dir.mkdir(parents=True, exist_ok=True)
    commits_data = [
        {
            "parent_sha": m.parent_sha,
            "merge_sha": m.merge_sha,
            "message": m.message,
            "diff": m.diff,
            "sub_commits": [
                {"sha": sc.sha, "message": sc.message, "diff": sc.diff}
                for sc in m.sub_commits
            ],
        }
        for m in merges
    ]
    path = data_dir / "merge_commits.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(commits_data, f, indent=2)
    print(f"Saved {len(commits_data)} merge commits to {path}")


def _select_merges_by_type(
    merges: list[MergeCommitInfo],
    max_tasks: int,
) -> list[tuple[MergeCommitInfo, str]]:
    """Classify merges and select up to max_tasks, aiming ~50% feature, ~30% bug, ~20% refactor."""
    n_b = round(0.3 * max_tasks)
    n_r = round(0.2 * max_tasks)
    n_f = max_tasks - n_b - n_r
    by_type = {COMMIT_TYPE_FEATURE: [], COMMIT_TYPE_BUG: [], COMMIT_TYPE_REFACTOR: []}
    for m in merges:
        try:
            ctype = classify_commit_type(m.message)
        except Exception as e:
            print(f"  Merge {m.merge_sha[:8]} classify error: {e}", file=sys.stderr)
            ctype = COMMIT_TYPE_FEATURE
        if ctype == COMMIT_TYPE_DO_NOT_USE:
            continue
        by_type[ctype].append((m, ctype))
        if (
            len(by_type[COMMIT_TYPE_FEATURE]) >= n_f
            and len(by_type[COMMIT_TYPE_BUG]) >= n_b
            and len(by_type[COMMIT_TYPE_REFACTOR]) >= n_r
        ):
            break
    selected = []
    selected.extend(by_type[COMMIT_TYPE_FEATURE][:n_f])
    selected.extend(by_type[COMMIT_TYPE_BUG][:n_b])
    selected.extend(by_type[COMMIT_TYPE_REFACTOR][:n_r])
    need_more = max_tasks - len(selected)
    if need_more > 0:
        remainder = (
            by_type[COMMIT_TYPE_FEATURE][n_f:]
            + by_type[COMMIT_TYPE_BUG][n_b:]
            + by_type[COMMIT_TYPE_REFACTOR][n_r:]
        )
        selected.extend(remainder[:need_more])
    return selected


def _build_tasks_from_merges(
    selected: list[tuple[MergeCommitInfo, str]],
    repo_map: str,
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Build task objects from selected (merge, type) pairs. Returns (tasks_by_type, tasks_list)."""
    tasks: dict[str, list[dict]] = {
        COMMIT_TYPE_FEATURE: [],
        COMMIT_TYPE_BUG: [],
        COMMIT_TYPE_REFACTOR: [],
    }
    for i, (m, ctype) in enumerate(selected, start=1):
        gt = extract_ground_truth(m.diff, m.message)
        try:
            prompt, difficulty = reverse_engineer_prompt(repo_map, m.message, m.diff)
        except Exception as e:
            print(f"  Merge {m.merge_sha[:8]} LLM error: {e}", file=sys.stderr)
            prompt = "Implement a change that is nice to have for this repo."
            difficulty = "Medium"
        obj = build_task_object(
            f"task_{i:03d}", prompt, m.parent_sha, gt, difficulty, task_type=ctype
        )
        tasks[ctype].append(obj)
    tasks_list = [t for lst in tasks.values() for t in lst]
    return tasks, tasks_list


def _write_tasks(tasks_list: list[dict], tasks: dict[str, list[dict]], data_dir: Path) -> None:
    """Write tasks_list to data_dir/tasks.json and print summary."""
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "tasks.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(tasks_list, f, indent=2)
    print(f"Wrote {len(tasks_list)} tasks to {out_path}")
    print(
        f"Feature: {len(tasks[COMMIT_TYPE_FEATURE])}, "
        f"Bug: {len(tasks[COMMIT_TYPE_BUG])}, Refactor: {len(tasks[COMMIT_TYPE_REFACTOR])}"
    )


def cmd_contextize(args):
    cfg = load_config()
    repo_url = args.repo_url or cfg.get("repo_url", "")
    if not repo_url:
        print("Error: repo_url required (set in config.yaml or pass --repo-url)", file=sys.stderr)
        sys.exit(1)
    branch = args.branch or cfg.get("branch", "main")
    print("Cloning repo...")
    clone_repo(repo_url, branch=branch)
    print("Building repo map with repomix...")
    get_repo_map_cached(repo_url, force_refresh=True)
    print("Done.")


def cmd_generate_tasks(args):
    cfg = load_config()
    set_run_log_subdir(args.run_id)
    data_dir = get_data_dir(args.run_id)
    repo_url = args.repo_url or cfg.get("repo_url", "")
    if not repo_url:
        print("Error: repo_url required", file=sys.stderr)
        sys.exit(1)
    repo_path = get_repo_path(repo_url)
    if not repo_path.exists():
        print("Error: repo not cloned. Run 'contextize' first.", file=sys.stderr)
        sys.exit(1)

    repo_map = get_repo_map_cached(repo_url)
    max_commits = args.max_commits or cfg.get("max_merge_commits", 100)
    max_tasks = args.max_tasks or cfg.get("max_tasks", 30)
    print(f"Extracting last {max_commits} merge commits...")
    merges = extract_merge_commits(repo_path, max_commits=max_commits)

    _save_merge_commits(merges, data_dir)

    print(f"Got {len(merges)} merges. Classifying by type (aiming for ~50% feature, ~30% bug, ~20% refactor)...")
    # shuffle the merges
    random.shuffle(merges)

    selected = _select_merges_by_type(merges, max_tasks)
    print(f"Selected {len(selected)} merges. Generating prompts and ground truth...")

    tasks, tasks_list = _build_tasks_from_merges(selected, repo_map)
    _write_tasks(tasks_list, tasks, data_dir)


def cmd_run_plans(args):
    cfg = load_config()
    repo_url = args.repo_url or cfg.get("repo_url", "")
    if not repo_url:
        print("Error: repo_url required", file=sys.stderr)
        sys.exit(1)
    data_dir = get_data_dir(args.run_id)
    tasks_path = data_dir / "tasks.json"
    if not tasks_path.exists():
        print("Error: tasks.json not found. Run 'generate-tasks' first.", file=sys.stderr)
        sys.exit(1)
    with open(tasks_path, encoding="utf-8") as f:
        tasks = json.load(f)
    print(f"Running plan mode for {len(tasks)} tasks...")
    run_plans_for_all_tasks(tasks, repo_url, plans_dir=data_dir)
    print(f"Done. Plans under data/{args.run_id}/plans/<task_id>/")


def cmd_grade(args):
    cfg = load_config()
    set_run_log_subdir(args.run_id)
    data_dir = get_data_dir(args.run_id)
    tasks_path = data_dir / "tasks.json"
    plans_dir = data_dir / "plans"
    if not tasks_path.exists():
        print("Error: tasks.json not found.", file=sys.stderr)
        sys.exit(1)
    with open(tasks_path, encoding="utf-8") as f:
        tasks = json.load(f)
    repo_map = ""
    repo_map_path = get_data_dir() / "repo_map.xml"  # shared, not run-scoped
    if repo_map_path.exists():
        repo_map = repo_map_path.read_text(encoding="utf-8")[:20000]
    results = []
    for task in tasks:
        task_id = task.get("task_id", "unknown")
        plan_path = plans_dir / task_id / "plan.md"
        if not plan_path.exists():
            results.append({"task_id": task_id, "score": 0, "error": "plan not found"})
            continue
        plan_text = plan_path.read_text(encoding="utf-8")
        steps = extract_claims(plan_text)
        verified_and_unknown_claim_ratio, unknown_claim_ratio, _ = verify_claims_via_search(steps, max_num_claims=cfg.get("max_num_claims_per_task", 3))
        logical_soundness = score_logical_soundness(plan_text, steps, repo_map)
        gt_metrics = compute_ground_truth_metrics(
            task, plan_text, repo_map=repo_map, data_dir=data_dir
        )
        quality = score_text_quality(plan_text)
        score, breakdown = aggregate_task_result(
            verified_and_unknown_claim_ratio, unknown_claim_ratio, logical_soundness, gt_metrics, quality
        )
        results.append({
            "task_id": task_id,
            "score": round(score, 2),
            "breakdown": breakdown,
        })
        print(f"Graded task {task_id} with score {score:.2f}. Breakdown: {breakdown}")
    out_path = data_dir / "scores.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    avg = sum(r["score"] for r in results if "score" in r) / len(results) if results else 0
    print(f"Graded {len(results)} tasks. Average score: {avg:.2f}. Wrote {out_path}")


def cmd_all(args):
    cmd_contextize(args)
    cmd_generate_tasks(args)
    cmd_run_plans(args)
    cmd_grade(args)


def main():
    parser = argparse.ArgumentParser(description="Plan Mode Eval pipeline")
    parser.add_argument("--repo-url", dest="repo_url", help="Repository URL (overrides config)")
    parser.add_argument("--branch", help="Branch (overrides config)")
    parser.add_argument("--run-id", dest="run_id", default=None, help="Log run id for LLM/search logs (default: run_YYYYMMDD_HHMMSS)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("contextize", help="Clone repo and build repo map")
    p_gen = sub.add_parser("generate-tasks", help="Generate tasks from merge commits")
    p_gen.add_argument("--max-commits", type=int, help="Max merge commits to consider")
    p_gen.add_argument("--max-tasks", type=int, help="Max tasks to output")
    sub.add_parser("run-plans", help="Run Claude Plan Mode for each task")
    sub.add_parser("grade", help="Grade plans and write scores.json")
    sub.add_parser("all", help="Run contextize -> generate-tasks -> run-plans -> grade")
    args = parser.parse_args()

    cfg = load_config()
    args.run_id = args.run_id or cfg.get("run_id", datetime.now().strftime("run_%Y%m%d_%H%M%S"))

    if args.command == "contextize":
        cmd_contextize(args)
    elif args.command == "generate-tasks":
        cmd_generate_tasks(args)
    elif args.command == "run-plans":
        cmd_run_plans(args)
    elif args.command == "grade":
        cmd_grade(args)
    elif args.command == "all":
        cmd_all(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
