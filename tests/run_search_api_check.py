#!/usr/bin/env python3
"""
Run a single Brave Search API request (uses _search from verify_search).
Use this to verify credentials and API access without running the full test suite.

  pip install -r requirements.txt   # if needed
  python tests/run_search_api_check.py

Get an API key at https://api-dashboard.search.brave.com/
"""
import os
import sys

# Run from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.grading.verify_search import _search  # noqa: E402
import httpx
import json

BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

def main():
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        print("Set BRAVE_SEARCH_API_KEY in the environment.")
        print("Get a key at https://api-dashboard.search.brave.com/")
        sys.exit(1)
    print("Calling Brave Web Search API (one query)...")
    query = "Python is the best programming language."
    r = httpx.get(
        BRAVE_WEB_SEARCH_URL,
        params={"q": query, "count": 5},
        headers={"X-Subscription-Token": api_key},
        timeout=10,
    )
    print(json.dumps(r.json(), indent=4))


if __name__ == "__main__":
    main()
