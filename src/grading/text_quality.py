"""Score plan text quality: conciseness, precision, tone, formatting (each 1-5 -> 0-1)."""
import re

import anthropic

from ..config import get_anthropic_api_key, get_project_root
from ..logging_utils import log_llm_call


def score_text_quality(plan_text: str, api_key: str | None = None) -> dict:
    """
    Return dict: conciseness, precision, tone, formatting (each 0-1).
    """
    api_key = api_key or get_anthropic_api_key()
    if not api_key:
        return {"conciseness": 0.5, "precision": 0.5, "tone": 0.5, "formatting": 0.5}
    root = get_project_root()
    path = root / "prompts" / "judge_style.txt"
    if path.exists():
        template = path.read_text(encoding="utf-8")
    else:
        template = "Evaluate: CONCISENESS, PRECISION, TONE, FORMATTING (1-5 each). Plan: {{plan}}"
    content = template.replace("{{plan}}", plan_text[:8000])
    model = "claude-sonnet-4-5"
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=256,
            messages=[{"role": "user", "content": content}],
        )
        text = (msg.content[0].text if msg.content else "").strip()
        log_llm_call(
            "score_text_quality",
            content,
            text,
            model=model,
            max_tokens=256,
        )
        def parse_score(name: str) -> float:
            m = re.search(rf"{name}\s*:\s*([1-5])", text, re.I)
            if m:
                return (int(m.group(1)) - 1) / 4.0
            return 0.5
        return {
            "conciseness": parse_score("CONCISENESS"),
            "precision": parse_score("PRECISION"),
            "tone": parse_score("TONE"),
            "formatting": parse_score("FORMATTING"),
        }
    except Exception as e:
        log_llm_call(
            "score_text_quality",
            content,
            "",
            model=model,
            max_tokens=256,
            extra={"error": str(e)},
        )
        return {"conciseness": 0.5, "precision": 0.5, "tone": 0.5, "formatting": 0.5}
