"""CLI: python -m receipts run|verify|tamper"""

import argparse
import io
import re
import sys
from pathlib import Path

from .config import RUNS_DIR


def _utf8_console():
    for stream in ("stdout", "stderr"):
        s = getattr(sys, stream)
        if isinstance(s, io.TextIOWrapper) and (s.encoding or "").lower() != "utf-8":
            s.reconfigure(encoding="utf-8")


def _run_dir(arg: str) -> Path:
    if arg == "last":
        runs = sorted((d for d in RUNS_DIR.iterdir() if (d / "head.sig").exists()), key=lambda d: (d / "head.sig").stat().st_mtime)
        if not runs:
            sys.exit("no runs yet")
        return runs[-1]
    path = Path(arg)
    return path if path.is_absolute() or path.exists() else RUNS_DIR / arg


def main(argv=None):
    _utf8_console()
    parser = argparse.ArgumentParser(prog="receipts", description="Diligence memos where every claim carries a verifiable receipt.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run diligence on a pitch")
    src = p_run.add_mutually_exclusive_group(required=True)
    src.add_argument("--pitch", type=Path, help="path to a text file with the pitch")
    src.add_argument("--text", help="pitch text inline")
    p_run.add_argument("--domain", help="company domain, if known")
    p_run.add_argument("--no-cache", action="store_true", help="always call the API live")

    p_ver = sub.add_parser("verify", help="verify a sealed run (no LLM)")
    p_ver.add_argument("run", help="run directory, run id, or 'last'")
    p_ver.add_argument("--witness", action="store_true", help="also check every call against Crustdata's usage log")

    p_tam = sub.add_parser("tamper", help="demo helper: flip one byte in a stored API response")
    p_tam.add_argument("run", help="run directory, run id, or 'last'")
    p_tam.add_argument("--receipt", type=int, help="receipt (ledger seq) to alter; default: first company enrich")

    p_sc = sub.add_parser("scout", help="scout new companies matching strategy/STRATEGY.md and seal predictions")
    p_sc.add_argument("--n", type=int, default=10, help="companies per round (default 10)")
    p_sc.add_argument("--round", type=int, help="round number (default: next)")
    p_sc.add_argument("--thesis", help='free-text thesis for this round, e.g. "Series A devtools in India"')

    p_an = sub.add_parser("analyze", help="analyse one company (name or website) against your strategy and learned preferences")
    p_an.add_argument("company", help='e.g. "stripe.com" or "Razorpay"')

    p_de = sub.add_parser("decide", help="record your picks for a scouting round; the agent scores itself and learns")
    p_de.add_argument("--round", type=int, required=True)
    p_de.add_argument("--pick", required=True, help="comma-separated table numbers or names, e.g. 2,5,7")

    p_view = sub.add_parser("view", help="build a clickable HTML view of a run (facts -> receipts -> raw JSON)")
    p_view.add_argument("run", help="run directory, run id, or 'last'")

    sub.add_parser("board", help="show the deal board")
    sub.add_parser("learned", help="show what the agent has learned about your preferences")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        from .agent import run
        pitch = args.pitch.read_text(encoding="utf-8") if args.pitch else args.text
        run(pitch, domain=args.domain, use_cache=not args.no_cache)
    elif args.cmd == "scout":
        from .scout import scout
        from .strategy import load_strategy
        strategy, text = load_strategy()
        scout(strategy, text, n=args.n, round_no=args.round, thesis_text=args.thesis)
    elif args.cmd == "analyze":
        from .scout import scout
        from .strategy import load_strategy
        strategy, text = load_strategy()
        scout(strategy, text, n=1, company_query=args.company)
    elif args.cmd == "decide":
        from .decide import decide
        from .strategy import load_strategy
        strategy, text = load_strategy()
        decide(strategy, text, args.round, args.pick)
    elif args.cmd == "board":
        _board()
    elif args.cmd == "view":
        from .view import build
        out = build(_run_dir(args.run))
        print(f"open {out}")
    elif args.cmd == "learned":
        from .decide import LEARNED_PATH
        print(LEARNED_PATH.read_text(encoding="utf-8") if LEARNED_PATH.exists() else "No decisions recorded yet.")
    elif args.cmd == "verify":
        from .verify import verify_run
        sys.exit(0 if verify_run(_run_dir(args.run), witness=args.witness) else 1)
    elif args.cmd == "tamper":
        _tamper(_run_dir(args.run), args.receipt)


def _board():
    from rich.table import Table

    from .board import all_deals, connect
    from .trace import console
    table = Table(title="Deal board")
    for col in ("Round", "Company", "Stage", "Agent", "p(pick)", "You", "Source"):
        table.add_column(col)
    for d in all_deals(connect()):
        table.add_row(str(d["round_no"] or "-"), f"{d['name']} ({d['domain'] or '-'})", d["stage"] or "-",
                      d["agent_recommendation"] or "-", f"{d['agent_probability']:.2f}" if d["agent_probability"] is not None else "-",
                      d["human_decision"] or "-", d["source"] or "-")
    console.print(table)


def _tamper(run_dir: Path, seq: int | None):
    from .ledger import read_ledger
    entries = [e for e in read_ledger(run_dir) if e.get("type") == "tool_call" and e.get("response_hash")]
    target = next((e for e in entries if e["seq"] == seq), None) if seq is not None else \
        next((e for e in entries if e["endpoint"] == "/company/enrich"), entries[0] if entries else None)
    if not target:
        sys.exit("no matching receipt")
    path = run_dir / "blobs" / "sha256" / target["response_hash"].split(":", 1)[1]
    data = path.read_text(encoding="utf-8")
    altered, n = re.subn(r'("total":\s*)(\d)', r"\g<1>9\2", data, count=1)
    if not n:
        altered = data[:-1] + " " + data[-1:]
    path.write_text(altered, encoding="utf-8")
    print(f"altered stored response for receipt #{target['seq']} ({target['endpoint']}): {path.name[:16]}…")
    if n:
        print("a headcount figure was quietly inflated (prefixed with a 9), as a dishonest operator might do")


if __name__ == "__main__":
    main()
