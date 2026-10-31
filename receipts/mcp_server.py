"""Receipts as an MCP server: any agent (Claude Code, Claude Desktop, ...) can screen deals and
verify claims through the same rulebook, receipts and signed trail.

    claude mcp add receipts -- python -m receipts.mcp_server
"""

import json
import os

os.environ.setdefault("RECEIPTS_MCP", "1")  # must be set before the trace console is created

from mcp.server.fastmcp import FastMCP  # noqa: E402

from . import board  # noqa: E402
from .config import RUNS_DIR  # noqa: E402
from .strategy import STRATEGY_PATH, load_strategy  # noqa: E402

mcp = FastMCP("receipts")


@mcp.tool()
def get_strategy() -> str:
    """Return the fund's rulebook (strategy/STRATEGY.md): thesis, tolerances, guardrails, autonomy limits and allowed actions."""
    return STRATEGY_PATH.read_text(encoding="utf-8")


@mcp.tool()
def check_pitch(pitch_text: str, domain: str | None = None) -> dict:
    """Verify every claim in a founder's pitch against Crustdata, decide (ADVANCE / REQUEST_INFO / PASS / NEEDS_HUMAN)
    under the rulebook, act (deal board, drafted email), and seal a signed run. Returns the verdicts and run id."""
    from .agent import run
    run_dir = run(pitch_text, domain=domain)
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    claims = json.loads((run_dir / "claims.json").read_text(encoding="utf-8"))
    return {"run_id": run_dir.name, "company": meta["resolution"], "decision": meta.get("decision"),
            "claims": [{k: c[k] for k in ("claim_id", "text", "status", "explanation")} for c in claims],
            "report": str(run_dir / "report.md")}


@mcp.tool()
def scout_round(n: int = 10) -> dict:
    """Scout n new companies matching the thesis, score them with the learned preference model, seal the predictions,
    and act within the autonomy limits. Returns the round table (decisions are left to the human)."""
    from .scout import scout
    strategy, text = load_strategy()
    run_id = scout(strategy, text, n=n)
    meta = json.loads((RUNS_DIR / run_id / "meta.json").read_text(encoding="utf-8"))
    rows = json.loads((RUNS_DIR / run_id / "round.json").read_text(encoding="utf-8"))
    return {"run_id": run_id, "round_no": meta["round_no"],
            "candidates": [{k: r[k] for k in ("n", "name", "domain", "probability", "recommendation", "rule", "auto_act", "why")}
                           for r in rows]}


@mcp.tool()
def record_decisions(round_no: int, picks: str) -> dict:
    """Record the HUMAN's picks for a scouting round (comma-separated table numbers or names). Only call this with
    choices the human actually made. Scores the agent against its sealed predictions and re-fits the preference model."""
    from .decide import decide
    strategy, text = load_strategy()
    run_id = decide(strategy, text, round_no, picks)
    meta = json.loads((RUNS_DIR / run_id / "meta.json").read_text(encoding="utf-8"))
    return {"run_id": run_id, "agreement": meta["agreement"], "learned": meta["learned"]}


@mcp.tool()
def verify_run(run_id: str, witness: bool = False) -> dict:
    """Deterministically re-verify a sealed run (chain, signature, receipts, facts, verdicts, actions, model).
    witness=True also checks every call against Crustdata's own usage log."""
    from .verify import verify_run as _verify
    return {"run_id": run_id, "verified": _verify(RUNS_DIR / run_id, witness=witness)}


@mcp.tool()
def deal_board() -> list[dict]:
    """Current deal board: stage, agent recommendation and probability, and human decision for every company."""
    return [{k: row[k] for k in ("company_id", "name", "domain", "round_no", "stage", "agent_recommendation",
                                 "agent_probability", "human_decision", "source")} for row in board.all_deals(board.connect())]


if __name__ == "__main__":
    mcp.run()
