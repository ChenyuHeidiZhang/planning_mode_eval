"""Verify claims via Google Custom Search and LLM comparison. Score: ratio verified, logical soundness."""
import os
import re

import anthropic
import httpx

from ..config import get_google_search_api_key, get_google_search_cx, get_anthropic_api_key


def _search(query: str, api_key: str, cx: str) -> str:
    """Return snippet from first result if any."""
    if not api_key or not cx:
        return ""
    url = "https://www.googleapis.com/customsearch/v1"
    params = {"key": api_key, "cx": cx, "q": query, "num": 1}
    try:
        r = httpx.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return ""
        data = r.json()
        items = data.get("items", [])
        if items:
            return items[0].get("snippet", "") or items[0].get("title", "")
    except Exception:
        pass
    return ""


def _verify_claim_with_llm(claim: str, snippet: str, api_key: str) -> str:
    """Return VERIFIED | HALLUCINATION | UNKNOWN."""
    if not api_key:
        return "UNKNOWN"
    client = anthropic.Anthropic(api_key=api_key)
    content = f"""Claim from plan: "{claim}"
Search result snippet: "{snippet}"

Does the snippet support the claim? Reply with exactly one word: VERIFIED, HALLUCINATION, or UNKNOWN (if unclear)."""
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=32,
            messages=[{"role": "user", "content": content}],
        )
        text = (msg.content[0].text if msg.content else "").strip().upper()
        if "VERIFIED" in text:
            return "VERIFIED"
        if "HALLUCINATION" in text:
            return "HALLUCINATION"
    except Exception:
        pass
    return "UNKNOWN"


def verify_claims_via_search(
    steps_with_claims: list[dict],
    api_key: str | None = None,
    google_key: str | None = None,
    google_cx: str | None = None,
) -> tuple[float, list[str]]:
    """
    For each claim, build query, search, compare with LLM. Return (ratio_verified, list of verdicts per claim).
    If Google API not configured, return (0.0, []) or treat all UNKNOWN.
    """
    api_key = api_key or get_anthropic_api_key()
    google_key = google_key or get_google_search_api_key()
    google_cx = google_cx or get_google_search_cx()
    verdicts = []
    all_claims = []
    for step in steps_with_claims:
        for c in step.get("claims", []) or []:
            if not c or not c.strip():
                continue
            all_claims.append(c)
            if not google_key or not google_cx:
                verdicts.append("UNKNOWN")
                continue
            query = c[:80].replace('"', "") if len(c) > 80 else c
            snippet = _search(query, google_key, google_cx)
            v = _verify_claim_with_llm(c, snippet, api_key) if snippet else "UNKNOWN"
            verdicts.append(v)
    if not verdicts:
        return 0.0, []
    verified = sum(1 for v in verdicts if v == "VERIFIED")
    return verified / len(verdicts), verdicts


def score_logical_soundness(
    plan_text: str,
    steps_with_claims: list[dict],
    repo_map: str,
    api_key: str | None = None,
) -> float:
    """
    LLM: Does step B require output step A doesn't produce? Is plan logically sound? Return 0-1.
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
Reply with SCORE: <0-1> (0=unsound, 1=sound) then one sentence."""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            messages=[{"role": "user", "content": content}],
        )
        text = (msg.content[0].text if msg.content else "").strip()
        m = re.search(r"SCORE:\s*([0-9.]+)", text, re.I)
        if m:
            return min(1.0, max(0.0, float(m.group(1))))
    except Exception:
        pass
    return 0.5
