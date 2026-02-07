"""Run repomix on a repo path and produce Repo Map XML."""
import subprocess
from pathlib import Path

from ..config import load_config, get_data_dir
from .clone import get_repo_path


def get_repo_map(repo_url: str | None = None, repo_path: Path | None = None, out_path: Path | None = None) -> str:
    """
    Invoke repomix on the cloned repo and return the Repo Map XML string.
    If out_path is set, also write the output there.
    Either repo_url (then we resolve repo path from data_dir) or repo_path must be given.
    """
    cfg = load_config()
    if repo_path is None:
        if not repo_url:
            raise ValueError("Either repo_url or repo_path is required")
        repo_path = get_repo_path(repo_url)
    if not repo_path.exists():
        raise FileNotFoundError(f"Repo path does not exist: {repo_path}")
    repomix_cmd = cfg.get("repomix_path", "npx")
    # npx repomix@latest <path> or repomix <path>
    if repomix_cmd == "npx":
        args = ["npx", "repomix@latest", "--style", "xml", str(repo_path)]
    else:
        args = [repomix_cmd, "--style", "xml", str(repo_path)]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=repo_path,
    )
    if result.returncode != 0:
        raise RuntimeError(f"repomix failed: {result.stderr or result.stdout}")
    xml_content = result.stdout
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(xml_content, encoding="utf-8")
    return xml_content


def get_repo_map_cached(repo_url: str, force_refresh: bool = False) -> str:
    """
    Get Repo Map, writing to data_dir/repo_map.xml and returning content.
    If force_refresh is False and file exists, read from file (caller must ensure repo is same).
    """
    data_dir = get_data_dir()
    cache_path = data_dir / "repo_map.xml"
    if not force_refresh and cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    content = get_repo_map(repo_url=repo_url, out_path=cache_path)
    return content
