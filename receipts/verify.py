"""Deterministic verifier: no LLM, no trust in the agent.

1. chain     every entry_hash recomputes, prev_hash links are intact, seq has no gaps
2. signature Ed25519 signature over the chain head is valid and matches the last entry
3. blobs     every stored API response re-hashes to the response_hash in its ledger entry
4. facts     every fact re-resolves (JSON Pointer) from its raw response to the same value
5. claims    every comparison re-runs to the same status and explanation
6. report    the memo re-renders byte-for-byte from claims + facts (no unbacked text or numbers)
7. witness   (optional) every live call matches Crustdata's own usage log for its X-Request-ID
"""

import json
import time
from pathlib import Path

import httpx

from .claims import evaluate
from .config import CRUSTDATA_API_VERSION, CRUSTDATA_BASE_URL, crustdata_api_key
from .facts import load_facts, resolve
from .ledger import canonical_json, entry_hash, read_blob, read_ledger, sha256_hex, verify_signature
from .render import render_report
from .trace import bad, console, info, ok


def verify_run(run_dir: Path, witness: bool = False) -> bool:
    console.rule(f"[bold]verify {run_dir.name}")
    results = []

    def check(name: str, passed: bool, detail: str):
        results.append(passed)
        (ok if passed else bad)(f"{name}: {detail}")

    entries = read_ledger(run_dir)

    # 1. chain
    broken = None
    prev = sha256_hex(entries[0]["run_id"].encode("utf-8")) if entries and entries[0].get("type") == "run_start" else None
    for i, e in enumerate(entries):
        if e.get("seq") != i:
            broken = f"sequence gap at entry #{i}"
            break
        if e.get("prev_hash") != prev:
            broken = f"prev_hash link broken at entry #{i}"
            break
        if entry_hash(e) != e.get("entry_hash"):
            broken = f"entry #{i} was modified (hash mismatch)"
            break
        prev = e["entry_hash"]
    check("chain", broken is None, broken or f"{len(entries)} entries, all links intact")

    # 2. signature
    sealed = json.loads((run_dir / "head.sig").read_text(encoding="utf-8"))
    sig_ok = verify_signature(sealed)
    head_ok = bool(entries) and sealed["head_hash"] == entries[-1]["entry_hash"] and sealed["entry_count"] == len(entries)
    check("signature", sig_ok and head_ok,
          "Ed25519 signature valid over chain head" if sig_ok and head_ok else
          ("signature invalid" if not sig_ok else "signed head does not match the ledger (entries added or removed)"))

    # 3. blobs
    calls = [e for e in entries if e.get("type") == "tool_call" and e.get("response_hash")]
    bad_blobs = []
    for e in calls:
        try:
            if sha256_hex(read_blob(run_dir, e["response_hash"])) != e["response_hash"]:
                bad_blobs.append(e["seq"])
        except FileNotFoundError:
            bad_blobs.append(e["seq"])
    check("blobs", not bad_blobs,
          f"{len(calls)}/{len(calls)} stored responses match their hashes" if not bad_blobs else
          f"response hash mismatch at receipt #{', #'.join(map(str, bad_blobs))} (stored API response was altered)")

    # 4. facts
    facts = load_facts(run_dir / "facts.json")
    by_seq = {e["seq"]: e for e in entries}
    bad_facts = []
    parsed = {}
    for fid, f in facts.items():
        entry = by_seq.get(f["receipt_seq"])
        if not entry or not entry.get("response_hash"):
            bad_facts.append(fid)
            continue
        if entry["seq"] not in parsed:
            try:
                parsed[entry["seq"]] = json.loads(read_blob(run_dir, entry["response_hash"]))
            except (FileNotFoundError, ValueError):
                parsed[entry["seq"]] = None
        if parsed[entry["seq"]] is None or resolve(parsed[entry["seq"]], f["pointer"]) != f["value"]:
            bad_facts.append(fid)
    check("facts", not bad_facts,
          f"{len(facts)} facts re-resolved from raw responses" if not bad_facts else f"facts not backed by their receipts: {', '.join(bad_facts)}")

    # 5. claims
    claim_set = next((e for e in reversed(entries) if e["type"] == "claim_set"), None)
    files_ok = claim_set is not None and all(
        sha256_hex((run_dir / name).read_bytes()) == claim_set[key]
        for name, key in (("claims.json", "claims_hash"), ("facts.json", "facts_hash"), ("meta.json", "meta_hash")))
    claims = json.loads((run_dir / "claims.json").read_text(encoding="utf-8"))
    mismatched = []
    for c in claims:
        if "unavailable_seq" in c:
            e = by_seq.get(c["unavailable_seq"])
            if not e or not (e.get("error") or e.get("type") == "decision"):
                mismatched.append(c["claim_id"])
            continue
        values = {name: (facts[fid]["value"] if fid else None) for name, fid in c["inputs"].items()}
        status, explanation = evaluate(c["type"], c["params"], values, c["inputs"])
        if status != c["status"] or explanation != c["explanation"]:
            mismatched.append(c["claim_id"])
    check("claims", files_ok and not mismatched,
          f"{len(claims)} verdicts reproduced by re-running the comparators" if files_ok and not mismatched else
          ("claims/facts/meta files differ from the hashes sealed in the ledger" if not files_ok else
           f"verdicts do not reproduce for {', '.join(mismatched)}"))

    # 6. report
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    report_entry = next((e for e in reversed(entries) if e["type"] == "report"), None)
    hash_ok = report_entry is not None and sha256_hex(report.encode("utf-8")) == report_entry["report_hash"]
    render_ok = render_report(meta, claims, facts) == report
    check("report", hash_ok and render_ok,
          "memo re-renders byte-for-byte from claims + facts; no unbacked text" if hash_ok and render_ok else
          ("memo was edited after sealing (hash mismatch)" if not hash_ok else "memo does not match what its claims and facts produce"))

    # 7. witness
    if witness:
        results.append(_witness(entries))

    passed = all(results)
    console.print()
    if passed:
        console.print("[bold green]VERIFIED: every statement in this memo traces to an unaltered, signed API receipt.[/]")
    else:
        console.print("[bold red]FAILED: this run has been altered or does not reproduce. Do not rely on the memo.[/]")
    return passed


def _witness(entries: list[dict]) -> bool:
    calls = [e for e in entries if e.get("type") == "tool_call" and e.get("upstream_request_id")]
    seen, failures = set(), []
    with httpx.Client(base_url=CRUSTDATA_BASE_URL, timeout=30,
                      headers={"authorization": f"Bearer {crustdata_api_key()}", "x-api-version": CRUSTDATA_API_VERSION}) as http:
        for e in calls:
            rid = e["upstream_request_id"]
            if rid in seen:
                continue
            seen.add(rid)
            resp = http.get(f"/account/usage/events/{rid}")
            time.sleep(1.05)  # usage endpoints allow 60 requests/minute
            if resp.status_code != 200:
                failures.append(f"#{e['seq']} not found in usage log (HTTP {resp.status_code})")
                continue
            event = resp.json()
            body = (event.get("request") or {}).get("body")
            problems = []
            if event.get("endpoint") != e["endpoint"]:
                problems.append("endpoint")
            if body is not None and canonical_json(body) != canonical_json(e["request"]):
                problems.append("request body")
            if e.get("http_status") and event.get("http_status") != e["http_status"]:
                problems.append("status")
            if e.get("credits_used") is not None and event.get("credits_used") is not None \
                    and abs(float(event["credits_used"]) - float(e["credits_used"])) > 1e-6:
                problems.append("credits")
            if problems:
                failures.append(f"#{e['seq']} differs from usage log ({', '.join(problems)})")
    passed = not failures
    (ok if passed else bad)(
        f"witness: {len(seen)}/{len(seen)} calls confirmed by Crustdata's usage log (endpoint, request body, status, credits)"
        if passed else "witness: " + "; ".join(failures[:5]))
    if passed:
        info("note: the usage log proves each call happened with these parameters; it does not store response bodies.")
    return passed
