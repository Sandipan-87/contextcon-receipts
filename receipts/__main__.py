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
        runs = sorted(RUNS_DIR.glob("run_*"))
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

    args = parser.parse_args(argv)
    if args.cmd == "run":
        from .agent import run
        pitch = args.pitch.read_text(encoding="utf-8") if args.pitch else args.text
        run(pitch, domain=args.domain, use_cache=not args.no_cache)
    elif args.cmd == "verify":
        from .verify import verify_run
        sys.exit(0 if verify_run(_run_dir(args.run), witness=args.witness) else 1)
    elif args.cmd == "tamper":
        _tamper(_run_dir(args.run), args.receipt)


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
