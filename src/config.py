"""Load config.yaml and .env for the pipeline."""
from pathlib import Path
import os
import yaml
from dotenv import load_dotenv

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_config_cache = None


def get_project_root() -> Path:
    return _PROJECT_ROOT


def load_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    path = _PROJECT_ROOT / "config.yaml"
    if not path.exists():
        _config_cache = _default_config()
        return _config_cache
    with open(path) as f:
        _config_cache = yaml.safe_load(f) or {}
    for key, default in _default_config().items():
        if key not in _config_cache:
            _config_cache[key] = default
    return _config_cache


def _default_config() -> dict:
    return {
        "repo_url": "",
        "branch": "main",
        "data_dir": "data",
        "repomix_path": "npx",
        "claude_cli_path": "claude",
        "repo_map_max_chars": 150000,
        "max_merge_commits": 100,
        "max_tasks": 30,
        "plan_timeout_seconds": 300,
    }


def get_data_dir() -> Path:
    cfg = load_config()
    d = cfg.get("data_dir", "data")
    p = Path(d)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    return p


def get_anthropic_api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "")


def get_google_search_api_key() -> str:
    return os.environ.get("GOOGLE_SEARCH_API_KEY", "")


def get_google_search_cx() -> str:
    return os.environ.get("GOOGLE_SEARCH_CX", "")
