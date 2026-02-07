"""Clone or shallow-clone a repo for the pipeline."""
import re
import subprocess
from pathlib import Path

from ..config import get_data_dir, load_config


def _repo_slug(repo_url: str) -> str:
    """e.g. https://github.com/owner/repo -> owner_repo"""
    url = repo_url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    parts = url.replace(":", "/").split("/")
    if len(parts) >= 2:
        return "_".join(parts[-2:])
    # fallback: sanitize
    return re.sub(r"[^\w.-]", "_", url.split("/")[-1] or "repo")


def clone_repo(repo_url: str, branch: str | None = None) -> Path:
    """
    Clone the repo into data_dir/repos/<owner>_<repo>/.
    Uses shallow clone with depth 500 so last 100 PRs have history.
    Returns path to the cloned repo root.
    """
    if not repo_url or not repo_url.strip():
        raise ValueError("repo_url is required")
    cfg = load_config()
    data_dir = get_data_dir()
    repos_dir = data_dir / "repos"
    repos_dir.mkdir(parents=True, exist_ok=True)
    slug = _repo_slug(repo_url)
    dest = repos_dir / slug
    depth = 500
    cmd = [
        "git",
        "clone",
        "--depth",
        str(depth),
        repo_url,
        str(dest),
    ]
    if branch:
        cmd.insert(-1, "--branch")
        cmd.insert(-1, branch)
    if dest.exists():
        # already cloned; optionally fetch more
        subprocess.run(
            ["git", "fetch", "--depth", str(depth)],
            cwd=dest,
            check=False,
            capture_output=True,
        )
        return dest
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return dest


def get_repo_path(repo_url: str) -> Path:
    """Return path to cloned repo (must have been cloned first)."""
    data_dir = get_data_dir()
    slug = _repo_slug(repo_url)
    return data_dir / "repos" / slug
