"""Crustdata REST client that records every call as a ledger receipt.

- Raw response bytes are stored as content-addressed blobs.
- X-Request-ID, X-Credits-Used and X-RateLimit-Remaining are captured for the witness check and budget.
- Successful responses are cached by request hash: dropped connections are still billed,
  so the same request is never paid for twice.
- Failed attempts are logged as receipts too, then retried with backoff.
"""

import json
import time
from dataclasses import dataclass

import httpx

from . import trace
from .config import CACHE_DIR, CRUSTDATA_API_VERSION, CRUSTDATA_BASE_URL, crustdata_api_key
from .ledger import Ledger, canonical_json, sha256_hex

MAX_ATTEMPTS = 4
RETRY_STATUSES = {429, 500, 502, 503, 504}


class ToolError(Exception):
    def __init__(self, endpoint: str, message: str, seq: int | None):
        super().__init__(f"{endpoint}: {message}")
        self.endpoint = endpoint
        self.seq = seq


@dataclass
class Receipt:
    seq: int
    endpoint: str
    data: object
    response_hash: str


class CrustdataClient:
    def __init__(self, ledger: Ledger, use_cache: bool = True, timeout: float = 60.0):
        self.ledger = ledger
        self.use_cache = use_cache
        self.credits_spent = 0.0
        self.http = httpx.Client(
            base_url=CRUSTDATA_BASE_URL,
            timeout=timeout,
            headers={
                "authorization": f"Bearer {crustdata_api_key()}",
                "x-api-version": CRUSTDATA_API_VERSION,
                "content-type": "application/json",
                "user-agent": "receipts-agent/0.1",
            },
        )
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def post(self, endpoint: str, body: dict, label: str = "") -> Receipt:
        request_hash = sha256_hex(canonical_json({"method": "POST", "endpoint": endpoint, "body": body}))
        cached = self._cache_get(request_hash) if self.use_cache else None
        if cached:
            return self._record_success(endpoint, body, request_hash, cached["raw"], cached["meta"], label, from_cache=True)

        last_error = "unknown error"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = self.http.post(endpoint, content=canonical_json(body))
            except httpx.TransportError as exc:
                last_error = f"transport error: {exc.__class__.__name__}"
                entry = self._record_failure(endpoint, body, request_hash, None, last_error, attempt)
                trace.warn(f"receipt #{entry['seq']} {endpoint} attempt {attempt} failed ({last_error}); retrying")
                time.sleep(min(2 ** attempt, 10))
                continue

            meta = {
                "http_status": resp.status_code,
                "upstream_request_id": resp.headers.get("x-request-id"),
                "credits_used": _float(resp.headers.get("x-credits-used")),
                "rate_limit_remaining": _int(resp.headers.get("x-ratelimit-remaining")),
                "upstream_ts": resp.headers.get("date"),
            }
            if resp.status_code == 200:
                self._cache_put(request_hash, resp.content, meta)
                return self._record_success(endpoint, body, request_hash, resp.content, meta, label, from_cache=False)

            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            entry = self._record_failure(endpoint, body, request_hash, meta, last_error, attempt)
            if resp.status_code not in RETRY_STATUSES:
                raise ToolError(endpoint, last_error, entry["seq"])
            wait = _int(resp.headers.get("retry-after")) or _int(resp.headers.get("x-ratelimit-reset")) or 2 ** attempt
            trace.warn(f"receipt #{entry['seq']} {endpoint} HTTP {resp.status_code}; retrying in {min(wait, 30)}s")
            time.sleep(min(wait, 30))

        raise ToolError(endpoint, last_error, self.ledger.entries[-1]["seq"])

    def _record_success(self, endpoint, body, request_hash, raw: bytes, meta: dict, label: str, from_cache: bool) -> Receipt:
        response_hash = self.ledger.store_blob(raw)
        entry = self.ledger.append(
            "tool_call",
            {
                "endpoint": endpoint,
                "request": body,
                "request_hash": request_hash,
                "response_hash": response_hash,
                "source": "cache" if from_cache else "live",
                **meta,
            },
        )
        if not from_cache:
            self.credits_spent += meta.get("credits_used") or 0.0
        credits = meta.get("credits_used")
        detail = f"{label} · {'cached' if from_cache else 'live'} · credits {credits if credits is not None else '?'}"
        trace.call(entry["seq"], endpoint, detail)
        return Receipt(seq=entry["seq"], endpoint=endpoint, data=json.loads(raw), response_hash=response_hash)

    def _record_failure(self, endpoint, body, request_hash, meta, error: str, attempt: int) -> dict:
        return self.ledger.append(
            "tool_call",
            {
                "endpoint": endpoint,
                "request": body,
                "request_hash": request_hash,
                "response_hash": None,
                "source": "live",
                "attempt": attempt,
                "error": error,
                **(meta or {"http_status": None, "upstream_request_id": None}),
            },
        )

    def _cache_get(self, request_hash: str):
        path = CACHE_DIR / (request_hash.split(":", 1)[1] + ".json")
        if not path.exists():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        return {"raw": record["raw"].encode("utf-8"), "meta": record["meta"]}

    def _cache_put(self, request_hash: str, raw: bytes, meta: dict) -> None:
        path = CACHE_DIR / (request_hash.split(":", 1)[1] + ".json")
        path.write_text(json.dumps({"raw": raw.decode("utf-8"), "meta": meta}), encoding="utf-8")


def _float(value):
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _int(value):
    try:
        return int(float(value)) if value is not None else None
    except ValueError:
        return None
