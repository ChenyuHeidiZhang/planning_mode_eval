"""Logging utilities for LLM calls and Google search queries/results."""
import json
import re
from datetime import datetime
from pathlib import Path

from .config import get_project_root


def _ensure_logs_dir() -> Path:
    """Ensure logs directory exists and return its path."""
    logs_dir = get_project_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _safe_filename(s: str, max_len: int = 50) -> str:
    """Create a filesystem-safe slug from a string."""
    slug = re.sub(r"[^\w\s-]", "", s)[:max_len].strip()
    slug = re.sub(r"[-\s]+", "_", slug)
    return slug or "unnamed"


def log_llm_call(
    call_type: str,
    prompt: str,
    response: str,
    *,
    model: str = "",
    max_tokens: int | None = None,
    extra: dict | None = None,
) -> Path:
    """
    Save an LLM call (prompt + response) to a log file in logs/.
    Returns the path to the created log file.
    """
    logs_dir = _ensure_logs_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_type = _safe_filename(call_type, 40)
    filename = f"llm_{safe_type}_{ts}.json"
    path = logs_dir / filename

    payload = {
        "call_type": call_type,
        "timestamp": datetime.now().isoformat(),
        "model": model,
        "prompt": prompt,
        "response": response,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if extra:
        payload["extra"] = extra

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def log_search(
    query: str,
    result: str,
    *,
    extra: dict | None = None,
) -> Path:
    """
    Save a Google search query and result to a log file in logs/.
    Returns the path to the created log file.
    """
    logs_dir = _ensure_logs_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _safe_filename(query[:60], 50)
    filename = f"search_{slug}_{ts}.json"
    path = logs_dir / filename

    payload = {
        "query": query,
        "result": result,
        "timestamp": datetime.now().isoformat(),
    }
    if extra:
        payload["extra"] = extra

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path
