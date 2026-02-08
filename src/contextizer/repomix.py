"""Run repomix on a repo path and produce Repo Map XML."""
import re
import subprocess
from pathlib import Path

from ..config import load_config, get_data_dir
from .clone import get_repo_path


def get_repo_map(repo_url: str | None = None, repo_path: Path | None = None, data_dir: Path | None = None) -> str:
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
    ignore_patterns = cfg.get("repomix_ignore", "")
    # npx repomix@latest <path> or repomix <path>
    if repomix_cmd == "npx":
        args = ["npx", "repomix@latest", "--style", "xml", str(repo_path), "--compress"]
    else:
        args = [repomix_cmd, "--style", "xml", str(repo_path), "--compress"]
    if ignore_patterns:
        # Normalize: strip newlines/extra spaces from YAML multiline
        patterns = "".join(ignore_patterns.split()).rstrip(",")
        args.extend(["--ignore", patterns])
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=data_dir,
    )
    if result.returncode != 0:
        raise RuntimeError(f"repomix failed: {result.stderr or result.stdout}")
    output_file = data_dir / "repomix-output.xml"
    if not output_file.exists():
        raise RuntimeError(f"repomix did not produce repomix-output.xml in {data_dir}")
    print('Repo map output file:', output_file)

    xml_content = output_file.read_text(encoding="utf-8")
    if cfg.get("repomix_exclude_files", False):
        xml_content = re.sub(r"<files>.*?</files>", "", xml_content, flags=re.DOTALL)
        compressed_output_file = data_dir / "repomix-output-compressed.xml"
        compressed_output_file.write_text(xml_content, encoding="utf-8")
        print('Compressed repo map output file:', compressed_output_file)

    # for logging
    cache_path = data_dir / "repomix_stdout.xml"
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(result.stdout, encoding="utf-8")
    return xml_content


def get_repo_map_cached(repo_url: str, force_refresh: bool = False) -> str:
    """
    Get Repo Map, writing to data_dir/repomix-output.xml and returning content.
    If force_refresh is False and file exists, read from file (caller must ensure repo is same).
    """
    data_dir = get_data_dir()
    cfg = load_config()
    if cfg.get("repomix_exclude_files", False):
        output_file = data_dir / "repomix-output-compressed.xml"
    else:
        output_file = data_dir / "repomix-output.xml"
    if not force_refresh and output_file.exists():
        return output_file.read_text(encoding="utf-8")
    content = get_repo_map(repo_url=repo_url, data_dir=data_dir)
    return content
