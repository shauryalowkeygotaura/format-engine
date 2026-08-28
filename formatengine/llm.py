"""Groq client. Free tier, JSON-mode, retry-aware.

Groq sits behind Cloudflare and rejects the default urllib User-Agent with a
403/1010, so the UA header below is required, not decorative.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from . import config


class LLMError(RuntimeError):
    pass


def chat(system: str, user: str, *, model: str | None = None,
         json_mode: bool = True, temperature: float = 0.4,
         max_tokens: int = 2000) -> str:
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise LLMError(
            "GROQ_API_KEY missing. Run under Doppler:\n"
            "  doppler run -p youtube-title-autoresearch -c dev -- python -m formatengine ..."
        )
    body = {
        "model": model or config.GROQ_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    req = urllib.request.Request(
        config.GROQ_URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",   # Cloudflare rejects urllib's default UA
        },
    )
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                if resp.status != 200:
                    raise LLMError(f"groq HTTP {resp.status}")
                raw = resp.read().decode("utf-8", "replace")
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503) and attempt < 2:
                last = detail
                time.sleep(3 * (attempt + 1))
                continue
            raise LLMError(f"groq HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            if attempt < 2:
                last = str(e.reason)
                time.sleep(2 ** attempt)
                continue
            raise LLMError(f"groq network error: {e.reason}") from e
    else:
        raise LLMError(f"groq failed after retries: {last}")

    try:
        data = json.loads(raw)
        return data["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        raise LLMError(f"unexpected groq response shape: {raw[:200]!r}") from e


def chat_json(system: str, user: str, **kw) -> dict:
    """chat() but the caller gets a dict or a clear error, never a string blob."""
    txt = chat(system, user, json_mode=True, **kw)
    try:
        out = json.loads(txt)
    except json.JSONDecodeError as e:
        raise LLMError(f"model returned non-JSON despite json_mode: {txt[:200]!r}") from e
    if not isinstance(out, dict):
        raise LLMError(f"model returned {type(out).__name__}, expected object")
    return out
