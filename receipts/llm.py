"""LLM access through Ollama (cloud API with OLLAMA_API_KEY, or a local daemon).

Models are tried in order (OLLAMA_MODELS, default "minimax-m3,gemma4:31b"): a model the account
cannot use (HTTP 402/404) is skipped, so the agent keeps working, and the model that actually
answered is returned so the run can record it in the ledger.
"""

import json
import os
import re

import httpx

from . import trace

CLOUD_URL = "https://ollama.com"
LOCAL_URL = "http://localhost:11434"


class LLMUnavailable(Exception):
    pass


_UNAVAILABLE: set[str] = set()  # models the account cannot use, skipped for the rest of the process


def models() -> list[str]:
    return [m.strip() for m in (os.environ.get("OLLAMA_MODELS") or "minimax-m3,gemma4:31b").split(",") if m.strip()]


def available() -> bool:
    return bool(os.environ.get("OLLAMA_API_KEY") or os.environ.get("OLLAMA_HOST"))


def chat_json(system: str, user: str, schema: dict, timeout: float = 120.0) -> tuple[dict, str]:
    """Structured JSON chat. Returns (parsed JSON, model used)."""
    content, model = _chat(system, user, schema, timeout)
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    return json.loads(text), model


def chat_text(system: str, user: str, timeout: float = 120.0) -> tuple[str, str]:
    return _chat(system, user, None, timeout)


def _chat(system, user, schema, timeout):
    key = os.environ.get("OLLAMA_API_KEY")
    base = os.environ.get("OLLAMA_HOST") or (CLOUD_URL if key else LOCAL_URL)
    headers = {"Authorization": f"Bearer {key}"} if key and base == CLOUD_URL else {}
    errors = []
    for model in [m for m in models() if m not in _UNAVAILABLE]:
        body = {"model": model, "stream": False, "options": {"temperature": 0},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if schema:
            body["format"] = schema
        for attempt in range(2):
            try:
                resp = httpx.post(f"{base}/api/chat", json=body, headers=headers, timeout=timeout)
            except httpx.TransportError as exc:
                errors.append(f"{model}: {exc.__class__.__name__}")
                continue
            if resp.status_code in (401, 402, 403, 404):
                errors.append(f"{model}: HTTP {resp.status_code}")
                _UNAVAILABLE.add(model)
                trace.warn(f"LLM {model} unavailable (HTTP {resp.status_code}); using the next model for this run")
                break
            if resp.status_code != 200:
                errors.append(f"{model}: HTTP {resp.status_code}")
                continue
            content = (resp.json().get("message") or {}).get("content") or ""
            if content.strip():
                return content, model
            errors.append(f"{model}: empty reply")
    raise LLMUnavailable("; ".join(errors) or "no models configured")
