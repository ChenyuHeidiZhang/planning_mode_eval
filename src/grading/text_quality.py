"""Score plan text quality: conciseness, precision, tone, formatting (each 1-5 -> 0-1)."""
import re

import anthropic

from ..config import get_anthropic_api_key, get_project_root


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
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            messages=[{"role": "user", "content": content}],
        )
        text = (msg.content[0].text if msg.content else "").strip()
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
    except Exception:
        return {"conciseness": 0.5, "precision": 0.5, "tone": 0.5, "formatting": 0.5}
