"""
CLI entrypoint: contextize, generate-tasks, run-plans, grade, all.
"""
import argparse
import json
import sys
from pathlib import Path

from .config import load_config, get_data_dir
from .contextizer import clone_repo
from .contextizer.repomix import get_repo_map_cached
from .task_gen.git_extract import extract_merge_commits
from .task_gen.ground_truth import extract_ground_truth
from .task_gen.llm_prompt import reverse_engineer_prompt, build_task_object
from .contextizer.clone import get_repo_path
from .runner.run_plan import run_plans_for_all_tasks
from .grading.claims import extract_claims
from .grading.verify_search import verify_claims_via_search, score_logical_soundness
from .grading.ground_truth_metrics import compute_ground_truth_metrics
from .grading.text_quality import score_text_quality
from .grading.aggregate import aggregate_task_result


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
    print("Done. Repo map written to data/repo_map.xml")


def cmd_generate_tasks(args):
    cfg = load_config()
    repo_url = args.repo_url or cfg.get("repo_url", "")
    if not repo_url:
        print("Error: repo_url required", file=sys.stderr)
        sys.exit(1)
    data_dir = get_data_dir()
    repo_path = get_repo_path(repo_url)
    if not repo_path.exists():
        print("Error: repo not cloned. Run 'contextize' first.", file=sys.stderr)
        sys.exit(1)
    repo_map = get_repo_map_cached(repo_url)
    max_commits = args.max_commits or cfg.get("max_merge_commits", 100)
    max_tasks = args.max_tasks or cfg.get("max_tasks", 30)
    print(f"Extracting last {max_commits} merge commits...")
    merges = extract_merge_commits(repo_path, max_commits=max_commits)
    print(f"Got {len(merges)} merges. Generating tasks (prompt + ground truth)...")
    tasks = []
    for i, m in enumerate(merges):
        gt = extract_ground_truth(m.diff, m.message)
        try:
            prompt, difficulty = reverse_engineer_prompt(repo_map, m.message, m.diff)
        except Exception as e:
            print(f"  Merge {m.merge_sha[:8]} LLM error: {e}", file=sys.stderr)
            prompt = "Implement the change suggested by the commit."
            difficulty = "Medium"
        task_id = f"task_{i+1:03d}"
        obj = build_task_object(task_id, prompt, m.parent_sha, gt, difficulty)
        tasks.append(obj)
        if len(tasks) >= max_tasks:
            break
    out_path = data_dir / "tasks.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2)
    print(f"Wrote {len(tasks)} tasks to {out_path}")


def cmd_run_plans(args):
    cfg = load_config()
    repo_url = args.repo_url or cfg.get("repo_url", "")
    if not repo_url:
        print("Error: repo_url required", file=sys.stderr)
        sys.exit(1)
    data_dir = get_data_dir()
    tasks_path = data_dir / "tasks.json"
    if not tasks_path.exists():
        print("Error: tasks.json not found. Run 'generate-tasks' first.", file=sys.stderr)
        sys.exit(1)
    with open(tasks_path, encoding="utf-8") as f:
        tasks = json.load(f)
    print(f"Running plan mode for {len(tasks)} tasks...")
    run_plans_for_all_tasks(tasks, repo_url, plans_dir=data_dir)
    print("Done. Plans under data/plans/<task_id>/")


def cmd_grade(args):
    cfg = load_config()
    data_dir = get_data_dir()
    tasks_path = data_dir / "tasks.json"
    plans_dir = data_dir / "plans"
    if not tasks_path.exists():
        print("Error: tasks.json not found.", file=sys.stderr)
        sys.exit(1)
    with open(tasks_path, encoding="utf-8") as f:
        tasks = json.load(f)
    repo_map = ""
    repo_map_path = data_dir / "repo_map.xml"
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
        claim_ratio, _ = verify_claims_via_search(steps)
        logical_soundness = score_logical_soundness(plan_text, steps, repo_map)
        gt_metrics = compute_ground_truth_metrics(task, plan_text, repo_map=repo_map)
        quality = score_text_quality(plan_text)
        score, breakdown = aggregate_task_result(
            claim_ratio, logical_soundness, gt_metrics, quality
        )
        results.append({
            "task_id": task_id,
            "score": round(score, 2),
            "breakdown": breakdown,
        })
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
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("contextize", help="Clone repo and build repo map")
    p_gen = sub.add_parser("generate-tasks", help="Generate tasks from merge commits")
    p_gen.add_argument("--max-commits", type=int, help="Max merge commits to consider")
    p_gen.add_argument("--max-tasks", type=int, help="Max tasks to output")
    sub.add_parser("run-plans", help="Run Claude Plan Mode for each task")
    sub.add_parser("grade", help="Grade plans and write scores.json")
    sub.add_parser("all", help="Run contextize -> generate-tasks -> run-plans -> grade")
    args = parser.parse_args()
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
