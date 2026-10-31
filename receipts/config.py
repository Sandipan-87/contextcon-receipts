"""Settings loaded from the environment and an optional .env file."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"
CACHE_DIR = ROOT / ".cache" / "responses"
KEYS_DIR = ROOT / "keys"

CRUSTDATA_BASE_URL = "https://api.crustdata.com"
CRUSTDATA_API_VERSION = "2025-11-01"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(ROOT / ".env")


def crustdata_api_key() -> str:
    key = os.environ.get("CRUSTDATA_API_KEY", "")
    if not key:
        raise RuntimeError("CRUSTDATA_API_KEY is not set (put it in .env)")
    return key


def anthropic_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or None


def anthropic_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL") or "claude-opus-5-5"
