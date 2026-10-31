"""Local web app: python -m receipts.webapp  ->  http://127.0.0.1:8000

The UI drives the same agent as the CLI. Long operations (scout, decide, pitch check, verify) run as
background jobs whose live trace streams to the browser, so you can watch the agent work.
"""

import io
import json
import re
import shutil
import threading
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from rich.console import Console

from . import board, trace
from .config import ROOT, RUNS_DIR
from .facts import load_facts, resolve
from .ledger import read_blob, read_ledger, verify_signature
from .strategy import STRATEGY_PATH, load_strategy

WEB = Path(__file__).parent / "web"
app = FastAPI(title="Receipts")
app.mount("/static", StaticFiles(directory=WEB), name="static")
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


# ---------------------------------------------------------------- jobs with live trace

class _LineSink(io.TextIOBase):
    def __init__(self, job):
        self.job, self.buf = job, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.job["log"].append(line)
        return len(s)


def start_job(kind: str, fn, *args) -> str:
    if not LOCK.acquire(blocking=False):
        raise HTTPException(409, "Another agent task is running; wait for it to finish.")
    job_id = uuid.uuid4().hex[:10]
    job = {"id": job_id, "kind": kind, "status": "running", "log": [], "result": None, "error": None}
    JOBS[job_id] = job

    def work():
        original = trace.console
        trace.console = Console(file=_LineSink(job), width=110, highlight=False, color_system=None, force_terminal=False)
        try:
            job["result"] = fn(*args)
            job["status"] = "done"
        except SystemExit as exc:
            job["status"], job["error"] = "error", str(exc)
        except Exception as exc:  # surface to the UI
            job["status"], job["error"] = "error", f"{exc.__class__.__name__}: {exc}"
            job["log"].append(traceback.format_exc())
        finally:
            trace.console = original
            LOCK.release()

    threading.Thread(target=work, daemon=True).start()
    return job_id


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, since: int = 0):
    job = JOBS.get(job_id) or {}
    if not job:
        raise HTTPException(404, "unknown job")
    return {**{k: job[k] for k in ("id", "kind", "status", "result", "error")}, "log": job["log"][since:], "next": len(job["log"])}


# ---------------------------------------------------------------- actions

class ScoutIn(BaseModel):
    n: int = 10
    thesis: str | None = None


class AnalyzeIn(BaseModel):
    query: str


class DecideIn(BaseModel):
    round_no: int
    picks: list[int]


class PitchIn(BaseModel):
    text: str
    domain: str | None = None


class VerifyIn(BaseModel):
    run_id: str
    witness: bool = False


@app.post("/api/scout")
def api_scout(body: ScoutIn):
    from .scout import scout
    strategy, text = load_strategy()
    return {"job": start_job("scout", lambda: scout(strategy, text, n=max(3, min(25, body.n)), thesis_text=body.thesis))}


@app.post("/api/analyze")
def api_analyze(body: AnalyzeIn):
    from .scout import scout
    if len(body.query.strip()) < 2:
        raise HTTPException(400, "Enter a company name or website.")
    strategy, text = load_strategy()
    return {"job": start_job("analyze", lambda: scout(strategy, text, n=1, company_query=body.query))}


@app.post("/api/decide")
def api_decide(body: DecideIn):
    from .decide import decide
    if not body.picks:
        raise HTTPException(400, "Pick at least one company.")
    strategy, text = load_strategy()
    return {"job": start_job("decide", lambda: decide(strategy, text, body.round_no, ",".join(map(str, body.picks))))}


@app.post("/api/pitch")
def api_pitch(body: PitchIn):
    from .agent import run
    if len(body.text.strip()) < 20:
        raise HTTPException(400, "Paste a pitch of at least a sentence or two.")
    return {"job": start_job("pitch", lambda: run(body.text, domain=(body.domain or None)).name)}


@app.post("/api/verify")
def api_verify(body: VerifyIn):
    from .verify import verify_run
    run_dir = _run_dir(body.run_id)
    return {"job": start_job("verify", lambda: verify_run(run_dir, witness=body.witness))}


@app.post("/api/tamper-demo")
def api_tamper(body: VerifyIn):
    """Copy the run, flip a byte in the copy's stored API response, and verify the copy. The original is untouched."""
    from .__main__ import _tamper
    from .verify import verify_run
    src = _run_dir(body.run_id)
    dst = RUNS_DIR.parent / ".tamper_demo" / src.name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    def work():
        _tamper(dst, None)
        trace.console.print("altered a copy of the run (original untouched); verifying the copy:")
        return verify_run(dst)
    return {"job": start_job("tamper", work)}


# ---------------------------------------------------------------- reads

@app.get("/api/strategy")
def api_strategy():
    rules, text = load_strategy()
    return {"text": text, "rules": rules}


@app.get("/api/board")
def api_board():
    return [dict(r) for r in board.all_deals(board.connect())]


@app.get("/api/runs")
def api_runs():
    runs = []
    for d in RUNS_DIR.iterdir():
        if not (d / "head.sig").exists() or not (d / "meta.json").exists():
            continue
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        kind = meta.get("kind", "pitch")
        title = {"scout": (f"Company analysis: {meta['single_company']}" if meta.get("single_company")
                           else f"Scouting round {meta.get('round_no')}"), "decide": f"Your decisions, round {meta.get('round_no')}",
                 "pitch": f"Pitch: {meta.get('resolution', {}).get('name') or meta.get('company_mention') or 'unknown'}"}[kind]
        runs.append({"run_id": d.name, "kind": kind, "title": title, "mtime": (d / "head.sig").stat().st_mtime,
                     "round_no": meta.get("round_no"), "decision": (meta.get("decision") or {}).get("decision")})
    return sorted(runs, key=lambda r: -r["mtime"])


@app.get("/api/rounds")
def api_rounds():
    runs = api_runs()
    decided = {r["round_no"]: r["run_id"] for r in runs if r["kind"] == "decide"}
    latest = {}
    for r in runs:
        if r["kind"] == "scout" and r["round_no"] not in latest:
            latest[r["round_no"]] = {**r, "decided_by": decided.get(r["round_no"])}
    return sorted(latest.values(), key=lambda r: -r["round_no"])


@app.get("/api/run/{run_id}")
def api_run(run_id: str):
    d = _run_dir(run_id)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    entries = read_ledger(d)
    sealed = json.loads((d / "head.sig").read_text(encoding="utf-8"))
    out = {"run_id": run_id, "meta": meta, "head_hash": sealed["head_hash"],
           "signature_ok": verify_signature(sealed) and sealed["head_hash"] == entries[-1]["entry_hash"],
           "actions": [e for e in entries if e["type"] in ("action", "action_blocked")],
           "decisions": [e for e in entries if e["type"] == "decision"],
           "calls": [{k: e.get(k) for k in ("seq", "endpoint", "source", "credits_used", "upstream_request_id", "http_status", "error")}
                     for e in entries if e["type"] == "tool_call"],
           "entry_count": len(entries)}
    if (d / "claims.json").exists():
        out["claims"] = json.loads((d / "claims.json").read_text(encoding="utf-8"))
    if (d / "round.json").exists():
        out["candidates"] = json.loads((d / "round.json").read_text(encoding="utf-8"))
    if (d / "facts.json").exists():
        out["facts"] = {fid: {k: f[k] for k in ("label", "receipt_seq", "pointer")} for fid, f in load_facts(d / "facts.json").items()}
    out["report_md"] = (d / "report.md").read_text(encoding="utf-8")
    return out


@app.get("/api/fact/{run_id}/{fid}")
def api_fact(run_id: str, fid: str):
    d = _run_dir(run_id)
    facts = load_facts(d / "facts.json")
    if fid not in facts:
        raise HTTPException(404, "unknown fact")
    f = facts[fid]
    entry = next(e for e in read_ledger(d) if e["seq"] == f["receipt_seq"])
    raw = json.loads(read_blob(d, entry["response_hash"]))
    resolved = resolve(raw, f["pointer"])
    return {"fact": f, "matches_raw": resolved == f["value"],
            "entry": {k: entry.get(k) for k in ("seq", "endpoint", "request", "source", "credits_used", "upstream_request_id",
                                                "response_hash", "entry_hash", "prev_hash", "ts")}}


@app.get("/api/learned")
def api_learned():
    from .scout import current_model
    rules, _ = load_strategy()
    model = current_model(rules)
    hist_path = ROOT / "data" / "agreement_history.json"
    history = json.loads(hist_path.read_text(encoding="utf-8")) if hist_path.exists() else []
    learned_path = ROOT / "strategy" / "LEARNED.md"
    summary = []
    if learned_path.exists():
        text = learned_path.read_text(encoding="utf-8")
        summary = [l[2:] for l in text.split("## Current preferences", 1)[-1].splitlines() if l.startswith("- ")]
    return {"model": {k: model[k] for k in ("weights", "bias", "n_decisions", "n_picks")},
            "prior": rules["learning"]["prior_weights"], "history": history, "summary": summary,
            "autonomy": rules["autonomy"]}


@app.get("/api/outbox")
def api_outbox():
    out = []
    for p in sorted(board.OUTBOX.glob("*.eml"), key=lambda p: -p.stat().st_mtime) if board.OUTBOX.exists() else []:
        text = p.read_text(encoding="utf-8")
        head, _, body = text.partition("\n\n")
        headers = dict(line.split(": ", 1) for line in head.splitlines() if ": " in line)
        out.append({"file": p.name, "subject": headers.get("Subject"), "to": headers.get("To"),
                    "run": headers.get("X-Receipts-Run"), "status": headers.get("X-Receipts-Status"), "body": body})
    return out


@app.get("/api/fixtures")
def api_fixtures():
    out = []
    for p in sorted((ROOT / "fixtures" / "pitches").glob("*.txt")):
        text = p.read_text(encoding="utf-8")
        body = "\n".join(l for l in text.splitlines() if not l.startswith("TEST FIXTURE")).strip()
        out.append({"name": p.stem.split("_", 1)[-1].replace("_", " "), "text": body})
    return out


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


def _run_dir(run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", run_id):
        raise HTTPException(400, "bad run id")
    d = RUNS_DIR / run_id
    if not d.exists():
        raise HTTPException(404, "unknown run")
    return d


def main():
    import uvicorn
    print("Receipts UI → http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
