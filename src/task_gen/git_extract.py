"""Extract last N merge commits with parent SHA, message, and full diff."""
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import load_config


@dataclass
class MergeCommitInfo:
    merge_sha: str
    parent_sha: str
    message: str
    diff: str


def extract_merge_commits(repo_path: Path, max_commits: int | None = None) -> list[MergeCommitInfo]:
    """
    Get last N merge commits. For each merge, parent = merge^, diff = git show merge.
    repo_path: path to cloned git repo.
    """
    cfg = load_config()
    n = max_commits or cfg.get("max_merge_commits", 100)
    # --merges: only merge commits. --first-parent: follow main line (merged PRs)
    log_out = subprocess.run(
        ["git", "log", "-n", str(n), "--merges", "--first-parent", "--format=%H"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    merge_shas = [h.strip() for h in log_out.stdout.strip().splitlines() if h.strip()]
    result = []
    for merge_sha in merge_shas:
        # parent of merge commit (first parent = target branch before merge)
        parent_out = subprocess.run(
            ["git", "rev-parse", f"{merge_sha}^"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if parent_out.returncode != 0:
            continue
        parent_sha = parent_out.stdout.strip()
        msg_out = subprocess.run(
            ["git", "log", "-1", "--format=%B", merge_sha],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        message = msg_out.stdout.strip()
        diff_out = subprocess.run(
            ["git", "show", merge_sha, "--no-renames", "--no-color", "--"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        diff = diff_out.stdout if diff_out.returncode == 0 else ""
        # skip if diff too large (binary or huge) or empty
        if len(diff) > 500_000:
            diff = diff[:500_000] + "\n... [truncated]"
        result.append(
            MergeCommitInfo(
                merge_sha=merge_sha,
                parent_sha=parent_sha,
                message=message,
                diff=diff,
            )
        )
    return result
