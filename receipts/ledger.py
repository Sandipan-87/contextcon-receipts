"""Append-only, hash-chained, Ed25519-signed run ledger with content-addressed blobs.

entry_hash = sha256(canonical_json(entry without entry_hash))
prev_hash  = previous entry's entry_hash (genesis uses sha256(run_id))
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from nacl.encoding import HexEncoder
from nacl.signing import SigningKey, VerifyKey

from .config import KEYS_DIR


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "entry_hash"}
    return sha256_hex(canonical_json(body))


def load_signing_key() -> SigningKey:
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    path = KEYS_DIR / "signing.key"
    if path.exists():
        return SigningKey(path.read_bytes().strip(), encoder=HexEncoder)
    key = SigningKey.generate()
    path.write_bytes(key.encode(encoder=HexEncoder))
    return key


class Ledger:
    def __init__(self, run_dir: Path, run_id: str, previous_head: str | None = None):
        self.run_dir = run_dir
        self.run_id = run_id
        self.blobs_dir = run_dir / "blobs" / "sha256"
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.path = run_dir / "ledger.jsonl"
        self.entries: list[dict] = []
        self.prev_hash = sha256_hex(run_id.encode("utf-8"))
        self.append("run_start", {"run_id": run_id, "previous_run_head": previous_head})

    def store_blob(self, data: bytes) -> str:
        digest = sha256_hex(data)
        (self.blobs_dir / digest.split(":", 1)[1]).write_bytes(data)
        return digest

    def append(self, entry_type: str, payload: dict) -> dict:
        entry = {"seq": len(self.entries), "type": entry_type, "ts": now_iso(), **payload, "prev_hash": self.prev_hash}
        entry["entry_hash"] = entry_hash(entry)
        self.entries.append(entry)
        self.prev_hash = entry["entry_hash"]
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
        return entry

    def seal(self) -> dict:
        key = load_signing_key()
        head = {"run_id": self.run_id, "head_hash": self.prev_hash, "entry_count": len(self.entries)}
        signature = key.sign(canonical_json(head)).signature
        sealed = {
            **head,
            "signature": signature.hex(),
            "public_key": key.verify_key.encode(encoder=HexEncoder).decode(),
            "algorithm": "ed25519",
        }
        (self.run_dir / "head.sig").write_text(json.dumps(sealed, indent=2), encoding="utf-8")
        return sealed


def verify_signature(sealed: dict) -> bool:
    head = {k: sealed[k] for k in ("run_id", "head_hash", "entry_count")}
    try:
        VerifyKey(sealed["public_key"], encoder=HexEncoder).verify(canonical_json(head), bytes.fromhex(sealed["signature"]))
        return True
    except Exception:
        return False


def read_ledger(run_dir: Path) -> list[dict]:
    with (run_dir / "ledger.jsonl").open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def read_blob(run_dir: Path, digest: str) -> bytes:
    return (run_dir / "blobs" / "sha256" / digest.split(":", 1)[1]).read_bytes()
