#!/usr/bin/env python3
"""Verify GroqCloud OpenAI-compatible chat completions connectivity (60s timeout).

Run manually by the operator; never executed by automated test suites.
"""
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

BASE_URL = (os.getenv("GROQ_BASE_URL") or os.getenv("LLM_BASE_URL") or "https://api.groq.com/openai/v1").rstrip("/")
API_KEY = (os.getenv("GROQ_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()
MODEL = (os.getenv("GROQ_MODEL") or os.getenv("LLM_MODEL") or "openai/gpt-oss-20b").strip()


def main():
    if not API_KEY:
        print("MISSING: GROQ_API_KEY is not configured in .env or environment.")
        sys.exit(1)

    endpoint = f"{BASE_URL}/chat/completions"
    print(f"Checking Groq endpoint: {endpoint}")
    print(f"Model: {MODEL}")
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                endpoint,
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": "Reply with the single word ok"}],
                    "max_tokens": 16,
                },
            )
    except httpx.TimeoutException:
        print("FAILED: Request timed out after 60 seconds.")
        sys.exit(1)
    except httpx.HTTPError as exc:
        print(f"FAILED: Network error: {type(exc).__name__}")
        sys.exit(1)

    print(f"HTTP Status: {resp.status_code}")
    if resp.is_success:
        data = resp.json()
        reported = data.get("model", "unknown")
        reply = ""
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            reply = str(choices[0].get("message", {}).get("content", "")).strip()
        print(f"Model Reported: {reported}")
        print(f"Reply: {reply}")
        print("OK: Groq connectivity verified.")
        sys.exit(0)

    print(f"FAILED: Provider returned HTTP {resp.status_code}: {resp.text[:300]}")
    sys.exit(1)


if __name__ == "__main__":
    main()

