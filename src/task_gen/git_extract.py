"""Extract last N merge commits with parent SHA, message, full diff, and sub-commits."""
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..config import load_config

DIFF_MAX_BYTES = 500_000
# Decode git output with replace so binary / non-UTF-8 in diffs doesn't crash us
GIT_TEXT_KW = {"text": True, "encoding": "utf-8", "errors": "replace"}
# When cleaning diffs, drop lines that contain this (from invalid UTF-8)
REPLACEMENT_CHAR = "\ufffd"


@dataclass
class SubCommitInfo:
    sha: str
    message: str
    diff: str


@dataclass
class MergeCommitInfo:
    merge_sha: str
    parent_sha: str
    message: str
    diff: str
    sub_commits: list[SubCommitInfo] = field(default_factory=list)


def _truncate_diff(diff: str, max_bytes: int = DIFF_MAX_BYTES) -> str:
    if len(diff) <= max_bytes:
        return diff
    return diff[:max_bytes] + "\n... [truncated]"


def _diff_drop_non_utf8(diff: str) -> str:
    """Remove lines that contain replacement chars (binary / non-UTF-8). Keeps only clean text."""
    if not diff:
        return diff
    return "\n".join(line for line in diff.splitlines() if REPLACEMENT_CHAR not in line)


def _get_sub_commit_shas(repo_path: Path, parent_sha: str, merge_sha: str) -> list[str]:
    """Return SHAs of commits in the merged branch (parent_sha..merge^2), newest first."""
    rev_parse = subprocess.run(
        ["git", "rev-parse", f"{merge_sha}^2"],
        cwd=repo_path,
        capture_output=True,
        **GIT_TEXT_KW,
    )
    if rev_parse.returncode != 0:
        return []
    tip_sha = rev_parse.stdout.strip()
    log_out = subprocess.run(
        ["git", "log", "--format=%H", f"{parent_sha}..{tip_sha}"],
        cwd=repo_path,
        capture_output=True,
        **GIT_TEXT_KW,
    )
    if log_out.returncode != 0:
        return []
    return [h.strip() for h in log_out.stdout.strip().splitlines() if h.strip()]


def _build_merge_message_and_diff(
    repo_path: Path,
    merge_message: str,
    sub_commits: list[SubCommitInfo],
    parent_sha: str,
    merge_sha: str,
) -> tuple[str, str]:
    """Build combined message and combined diff for the merge."""
    parts = [merge_message]
    if sub_commits:
        parts.append("\n--- Commits in this merge ---")
        for sc in sub_commits:
            parts.append(f"\nCommit {sc.sha[:8]}: {sc.message.strip()}")
    message = "\n".join(parts)

    diff_out = subprocess.run(
        ["git", "diff", parent_sha, f"{merge_sha}^2", "--no-renames", "--no-color", "--"],
        cwd=repo_path,
        capture_output=True,
        **GIT_TEXT_KW,
    )
    diff = diff_out.stdout if diff_out.returncode == 0 else ""
    diff = _truncate_diff(_diff_drop_non_utf8(diff))
    return message, diff


# TODO: extract commits randomly instead of last N.
def extract_merge_commits(repo_path: Path, max_commits: int | None = None) -> list[MergeCommitInfo]:
    """
    Get last N merge commits. For each merge we include:
    - parent_sha (first parent), merge_sha
    - message: merge message + all sub-commit messages (commits in the merged branch)
    - diff: combined diff of the merged branch (parent_sha..merge^2)
    - sub_commits: list of {sha, message, diff} for each commit in the merge
    """
    cfg = load_config()
    n = max_commits or cfg.get("max_merge_commits", 100)
    # --merges: only merge commits. --first-parent: follow main line (merged PRs)
    log_out = subprocess.run(
        ["git", "log", "-n", str(n), "--merges", "--first-parent", "--format=%H"],
        cwd=repo_path,
        capture_output=True,
        check=True,
        **GIT_TEXT_KW,
    )
    merge_shas = [h.strip() for h in log_out.stdout.strip().splitlines() if h.strip()]
    result = []
    for merge_sha in merge_shas:
        parent_out = subprocess.run(
            ["git", "rev-parse", f"{merge_sha}^"],
            cwd=repo_path,
            capture_output=True,
            **GIT_TEXT_KW,
        )
        if parent_out.returncode != 0:
            continue
        parent_sha = parent_out.stdout.strip()

        merge_msg_out = subprocess.run(
            ["git", "log", "-1", "--format=%B", merge_sha],
            cwd=repo_path,
            capture_output=True,
            check=True,
            **GIT_TEXT_KW,
        )
        merge_message = merge_msg_out.stdout.strip()

        sub_shas = _get_sub_commit_shas(repo_path, parent_sha, merge_sha)
        sub_commits: list[SubCommitInfo] = []
        for sha in sub_shas:
            msg_out = subprocess.run(
                ["git", "log", "-1", "--format=%B", sha],
                cwd=repo_path,
                capture_output=True,
                **GIT_TEXT_KW,
            )
            msg = msg_out.stdout.strip() if msg_out.returncode == 0 else ""
            diff_out = subprocess.run(
                ["git", "show", sha, "--no-renames", "--no-color", "--"],
                cwd=repo_path,
                capture_output=True,
                **GIT_TEXT_KW,
            )
            diff = diff_out.stdout if diff_out.returncode == 0 else ""
            diff = _truncate_diff(_diff_drop_non_utf8(diff))
            sub_commits.append(SubCommitInfo(sha=sha, message=msg, diff=diff))

        message, diff = _build_merge_message_and_diff(
            repo_path, merge_message, sub_commits, parent_sha, merge_sha
        )

        result.append(
            MergeCommitInfo(
                merge_sha=merge_sha,
                parent_sha=parent_sha,
                message=message,
                diff=diff,
                sub_commits=sub_commits,
            )
        )
    return result
