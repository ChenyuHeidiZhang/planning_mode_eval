"""Verify claims via Brave Search API and LLM comparison. Score: 1 - contradiction ratio, logical soundness."""
import os
import re

import anthropic
import httpx

from ..config import get_brave_search_api_key, get_anthropic_api_key
from ..logging_utils import log_llm_call, log_search

BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


def _search(query: str, api_key: str) -> str:
    """Return concatenated snippets (description or title) from first 5 Brave web search results if any."""
    if not api_key:
        return ""
    try:
        r = httpx.get(
            BRAVE_WEB_SEARCH_URL,
            params={"q": query, "count": 5},
            headers={"X-Subscription-Token": api_key},
            timeout=10,
        )
        if r.status_code != 200:
            log_search(query, "", extra={"status_code": r.status_code, "error": r.text[:500] if r.text else ""})
            return ""
        data = r.json()
        results = (data.get("web") or {}).get("results") or []
        if results:
            snippets = []
            for res in results[:5]:
                s = res.get("description") or res.get("title") or ""
                if s:
                    snippets.append(s)
            snippet = "\n".join(snippets)
            log_search(query, snippet, extra={"num_results": len(results)})
            return snippet
        log_search(query, "", extra={"num_results": 0})
    except Exception as e:
        log_search(query, "", extra={"error": str(e)})
    return ""


def _verify_claim_with_llm(claim: str, snippet: str, api_key: str) -> str:
    """Return VERIFIED | CONTRADICTED | UNKNOWN."""
    if not api_key:
        return "UNKNOWN"
    client = anthropic.Anthropic(api_key=api_key)
    content = f"""Claim from plan: "{claim}"
Search result snippet: "{snippet}"

Does the snippet support the claim or contradict it? Reply with exactly one word: VERIFIED, CONTRADICTED, or UNKNOWN (if unclear)."""
    model = "claude-sonnet-4-5"
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=32,
            messages=[{"role": "user", "content": content}],
        )
        text = (msg.content[0].text if msg.content else "").strip().upper()
        log_llm_call(
            "verify_claim",
            content,
            text,
            model=model,
            max_tokens=32,
            extra={"claim": claim[:200], "snippet": snippet[:200], "verdict": text[:50]},
        )
        if "VERIFIED" in text:
            return "VERIFIED"
        if "CONTRADICTED" in text:
            return "CONTRADICTED"
    except Exception as e:
        log_llm_call(
            "verify_claim",
            content,
            "",
            model=model,
            max_tokens=32,
            extra={"claim": claim[:200], "error": str(e)},
        )
    return "UNKNOWN"


def verify_claims_via_search(
    steps_with_claims: list[dict],
    max_num_claims: int,
    api_key: str | None = None,
    search_api_key: str | None = None,
) -> tuple[float, list[str]]:
    """
    For each claim, build query, search (Brave), compare with LLM. Return (1 - contradiction_ratio, unknown_ratio, verdicts).
    If Brave Search API not configured, treat all UNKNOWN.
    """
    api_key = api_key or get_anthropic_api_key()
    search_api_key = search_api_key or get_brave_search_api_key()
    verdicts = []
    all_claims = []
    for step in steps_with_claims:
        for c in step.get("claims", []) or []:
            if not c or not c.strip():
                continue
            all_claims.append(c)
            if len(all_claims) >= max_num_claims:
                break
            if not search_api_key:
                verdicts.append("UNKNOWN")
                continue
            query = c[:80].replace('"', "") if len(c) > 80 else c
            snippet = _search(query, search_api_key)
            v = _verify_claim_with_llm(c, snippet, api_key) if snippet else "UNKNOWN"
            verdicts.append(v)

    contradicted = sum(1 for v in verdicts if v == "CONTRADICTED")
    unknown = sum(1 for v in verdicts if v == "UNKNOWN")
    n = len(verdicts)
    claim_ratio = 1.0 - (contradicted / n) if n else 0.0
    return claim_ratio, unknown / n if n else 0.0, verdicts


def score_logical_soundness(
    plan_text: str,
    steps_with_claims: list[dict],
    repo_map: str,
    api_key: str | None = None,
) -> float:
    """
    LLM: Does step B require output step A doesn't produce? Is plan logically sound? Prompt uses 1-5 scale; returns 0-1 for pipeline.
    """
    api_key = api_key or get_anthropic_api_key()
    if not api_key:
        return 0.5
    steps_summary = "\n".join(
        f"Step {i+1}: {s.get('intent', '')}" for i, s in enumerate(steps_with_claims)
    )
    content = f"""Repo context (excerpt): {repo_map[:8000]}

Plan steps:
{steps_summary}

Full plan (excerpt): {plan_text[:6000]}

Evaluate: (1) Does any step require an output that a previous step fails to produce? (2) Is the overall plan logically sound and does it solve the problem?
Reply with SCORE: <1-5> (1=very unsound, 5=very sound) then one sentence."""
    model = "claude-opus-4-6"
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=256,
            messages=[{"role": "user", "content": content}],
        )
        text = (msg.content[0].text if msg.content else "").strip()
        log_llm_call(
            "logical_soundness",
            content,
            text,
            model=model,
            max_tokens=256,
        )
        m = re.search(r"SCORE:\s*([0-9.]+)", text, re.I)
        if m:
            raw = float(m.group(1))
            # Normalize 1-5 to 0-1 for pipeline
            if raw <= 5 and raw >= 1:
                return (raw - 1) / 4.0
            return min(1.0, max(0.0, raw))
    except Exception as e:
        log_llm_call(
            "logical_soundness",
            content,
            "",
            model=model,
            max_tokens=256,
            extra={"error": str(e)},
        )
    return 0.5
