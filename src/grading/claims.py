"""Extract atomic steps and verifiable claims from a plan using LLM."""
import json
import re
from pathlib import Path

import anthropic

from ..config import get_anthropic_api_key, get_project_root
from ..logging_utils import log_llm_call


def _load_template() -> str:
    root = get_project_root()
    path = root / "prompts" / "claim_extract.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return """Parse the plan into steps with intent and verifiable claims. Output JSON: {"steps": [{"intent": "...", "claims": ["..."]}]}
Plan:
{{plan}}
"""


def extract_claims(plan_text: str, api_key: str | None = None) -> list[dict]:
    """
    Return list of {"intent": str, "claims": list[str]}.
    """
    api_key = api_key or get_anthropic_api_key()
    if not api_key:
        return []
    template = _load_template()
    content = template.replace("{{plan}}", plan_text[:50000])
    model = "claude-sonnet-4-20250514"
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": content}],
    )
    text = msg.content[0].text if msg.content else ""
    log_llm_call(
        "extract_claims",
        content,
        text,
        model=model,
        max_tokens=2048,
    )
    # Extract JSON (allow wrapped in ```json ... ```)
    json_str = text.strip()
    m = re.search(r"\{[\s\S]*\"steps\"[\s\S]*\}", text)
    if m:
        json_str = m.group(0)
    try:
        data = json.loads(json_str)
        steps = data.get("steps", [])
        return [{"intent": s.get("intent", ""), "claims": s.get("claims", []) or []} for s in steps]
    except json.JSONDecodeError:
        return []
