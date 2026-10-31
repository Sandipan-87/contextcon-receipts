"""The fund's deal board (local SQLite CRM) and the outbox of drafted emails.

The board is working state; the signed run ledgers are the source of truth. Every board change
is made through actions.execute(), which records it in the current run's ledger.
"""

import json
import sqlite3
from datetime import datetime, timezone

from .config import ROOT

DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "dealboard.db"
OUTBOX = ROOT / "outbox"

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    company_id INTEGER PRIMARY KEY,
    name TEXT, domain TEXT,
    source TEXT,                 -- scout | pitch
    round_no INTEGER,
    stage TEXT,                  -- Scouted | Needs analyst | Partner meeting | Awaiting founder info | Passed
    agent_recommendation TEXT,
    agent_probability REAL,
    agent_confidence REAL,
    human_decision TEXT,         -- pick | reject | NULL
    features TEXT,               -- JSON feature vector used for learning
    last_run_id TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    ts TEXT, company_id INTEGER, run_id TEXT, event TEXT, detail TEXT
);
"""


def connect(path=DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert(conn, company_id: int, run_id: str, **fields) -> None:
    fields = {k: (json.dumps(v) if k == "features" and v is not None else v) for k, v in fields.items()}
    existing = conn.execute("SELECT company_id FROM deals WHERE company_id = ?", (company_id,)).fetchone()
    fields["last_run_id"], fields["updated_at"] = run_id, now()
    if existing:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE deals SET {sets} WHERE company_id = ?", (*fields.values(), company_id))
    else:
        cols = ", ".join(["company_id", *fields])
        conn.execute(f"INSERT INTO deals ({cols}) VALUES ({', '.join('?' * (len(fields) + 1))})", (company_id, *fields.values()))
    conn.commit()


def log_event(conn, company_id, run_id, event, detail) -> None:
    conn.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?)", (now(), company_id, run_id, event, detail))
    conn.commit()


def seen_company_ids(conn) -> set[int]:
    return {r["company_id"] for r in conn.execute("SELECT company_id FROM deals")}


def training_rows(conn) -> list[dict]:
    rows = conn.execute("SELECT company_id, name, features, human_decision, round_no FROM deals "
                        "WHERE human_decision IN ('pick', 'reject') AND features IS NOT NULL ORDER BY round_no, company_id")
    return [{"company_id": r["company_id"], "name": r["name"], "features": json.loads(r["features"]),
             "label": 1 if r["human_decision"] == "pick" else 0, "round_no": r["round_no"]} for r in rows]


def all_deals(conn) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM deals ORDER BY round_no, stage, name"))
