"""Deterministic verifier: no LLM, no trust in the agent.

Every run:  chain · signature · blobs · facts · actions (rule-permitted, drafted emails grounded)
pitch run:  claims re-evaluated with the sealed tolerances · memo re-rendered byte-for-byte
scout run:  features recomputed from facts · predictions recomputed from the sealed model · report re-rendered
decide run: sealed predictions re-checked · agreement recomputed · model re-fitted from the training set
--witness:  every live API call matches Crustdata's usage log for its X-Request-ID
"""

import json
import time
from pathlib import Path

import httpx

from . import learn
from .claims import evaluate
from .compose import grounded
from .config import CRUSTDATA_API_VERSION, CRUSTDATA_BASE_URL, RUNS_DIR, crustdata_api_key
from .facts import load_facts, resolve
from .features import compute
from .ledger import canonical_json, entry_hash, read_blob, read_ledger, sha256_hex, verify_signature
from .render import render_decision, render_report, render_round
from . import trace
from .trace import bad, info, ok


def verify_run(run_dir: Path, witness: bool = False) -> bool:
    trace.console.rule(f"[bold]verify {run_dir.name}")
    results = []

    def check(name: str, passed: bool, detail: str):
        results.append(passed)
        (ok if passed else bad)(f"{name}: {detail}")

    entries = read_ledger(run_dir)
    by_seq = {e["seq"]: e for e in entries}
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    kind = meta.get("kind", "pitch")

    # chain
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

    # signature
    sealed = json.loads((run_dir / "head.sig").read_text(encoding="utf-8"))
    sig_ok = verify_signature(sealed)
    head_ok = bool(entries) and sealed["head_hash"] == entries[-1]["entry_hash"] and sealed["entry_count"] == len(entries)
    check("signature", sig_ok and head_ok,
          "Ed25519 signature valid over chain head" if sig_ok and head_ok else
          ("signature invalid" if not sig_ok else "signed head does not match the ledger (entries added or removed)"))

    # blobs
    calls = [e for e in entries if e.get("type") == "tool_call" and e.get("response_hash")]
    bad_blobs = []
    for e in calls:
        try:
            if sha256_hex(read_blob(run_dir, e["response_hash"])) != e["response_hash"]:
                bad_blobs.append(e["seq"])
        except FileNotFoundError:
            bad_blobs.append(e["seq"])
    if calls:
        check("blobs", not bad_blobs,
              f"{len(calls)}/{len(calls)} stored API responses match their hashes" if not bad_blobs else
              f"response hash mismatch at receipt #{', #'.join(map(str, bad_blobs))} (stored API response was altered)")

    # facts
    facts = load_facts(run_dir / "facts.json") if (run_dir / "facts.json").exists() else {}
    if facts:
        bad_facts, parsed = [], {}
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
        check("facts", not bad_facts, f"{len(facts)} facts re-resolved from raw responses" if not bad_facts
              else f"facts not backed by their receipts: {', '.join(bad_facts[:8])}")

    # sealed files
    claim_set = next((e for e in reversed(entries) if e["type"] == "claim_set"), None)
    files = {"claims.json": "claims_hash", "facts.json": "facts_hash", "meta.json": "meta_hash", "round.json": "round_hash"}
    files_ok = claim_set is not None and all(sha256_hex((run_dir / name).read_bytes()) == claim_set[key]
                                             for name, key in files.items() if key in claim_set)

    if kind == "pitch":
        _verify_pitch(run_dir, meta, facts, by_seq, files_ok, entries, check)
    elif kind == "scout":
        _verify_scout(run_dir, meta, facts, entries, files_ok, check)
    elif kind == "decide":
        _verify_decide(run_dir, meta, entries, files_ok, check)

    # actions
    actions = [e for e in entries if e["type"] == "action"]
    if actions:
        allowed = _sealed_allowed_actions(entries)
        not_allowed = [e["seq"] for e in actions if e["action"] not in allowed]
        ungrounded = [e["seq"] for e in actions if e["action"] == "draft_email_to_outbox" and e.get("author", "").startswith("llm")
                      and not grounded(e["body"], "\n".join(e.get("grounding_facts", [])) + "\n" + str(e.get("subject")))]
        blocked = sum(1 for e in entries if e["type"] == "action_blocked")
        check("actions", not not_allowed and not ungrounded,
              f"{len(actions)} actions, each permitted by the sealed STRATEGY.md; drafted emails use only grounded numbers"
              + (f"; {blocked} forbidden action(s) blocked" if blocked else "") if not not_allowed and not ungrounded else
              f"actions outside the rulebook at #{not_allowed}" if not_allowed else f"ungrounded numbers in drafted email(s) at #{ungrounded}")

    report = (run_dir / "report.md").read_text(encoding="utf-8")
    report_entry = next((e for e in reversed(entries) if e["type"] == "report"), None)
    if report_entry and sha256_hex(report.encode("utf-8")) != report_entry["report_hash"]:
        check("report hash", False, "report was edited after sealing")

    if witness:
        results.append(_witness(entries))

    passed = all(results)
    trace.console.print()
    if passed:
        trace.console.print("[bold green]VERIFIED: every statement and action in this run traces to unaltered, signed receipts and rules.[/]")
    else:
        trace.console.print("[bold red]FAILED: this run has been altered or does not reproduce. Do not rely on it.[/]")
    return passed


def _verify_pitch(run_dir, meta, facts, by_seq, files_ok, entries, check):
    claims = json.loads((run_dir / "claims.json").read_text(encoding="utf-8"))
    mismatched = []
    for c in claims:
        if "unavailable_seq" in c:
            e = by_seq.get(c["unavailable_seq"])
            if not e or not (e.get("error") or e.get("type") == "decision"):
                mismatched.append(c["claim_id"])
            continue
        values = {name: (facts[fid]["value"] if fid else None) for name, fid in c["inputs"].items()}
        status, explanation = evaluate(c["type"], c["params"], values, c["inputs"], c.get("tol"))
        if status != c["status"] or explanation != c["explanation"]:
            mismatched.append(c["claim_id"])
    check("claims", files_ok and not mismatched,
          f"{len(claims)} verdicts reproduced with the sealed tolerances" if files_ok and not mismatched else
          ("claims/facts/meta files differ from the hashes sealed in the ledger" if not files_ok else
           f"verdicts do not reproduce for {', '.join(mismatched)}"))
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    check("report", render_report(meta, claims, facts) == report,
          "memo re-renders byte-for-byte from claims + facts; no unbacked text")


def _verify_scout(run_dir, meta, facts, entries, files_ok, check):
    candidates = json.loads((run_dir / "round.json").read_text(encoding="utf-8"))
    model_entry = next(e for e in entries if e["type"] == "model_state")
    model_ok = model_entry["model"] == meta["model"]
    bad = []
    for c in candidates:
        values = {k: (facts[fid]["value"] if fid else None) for k, fid in c["refs"].items()}
        values["company_id"] = c["company_id"]
        feats = compute(values, meta["as_of"])
        pred = learn.predict(meta["model"], feats["vector"])
        if feats["vector"] != c["vector"] or feats["raw"] != c["raw"] or abs(pred["probability"] - c["probability"]) > 1e-9:
            bad.append(c["n"])
    check("features & scores", files_ok and model_ok and not bad,
          f"{len(candidates)} feature vectors recomputed from facts and re-scored with the sealed model" if files_ok and model_ok and not bad
          else ("sealed files or model differ" if not (files_ok and model_ok) else f"rows {bad} do not reproduce"))
    pred_entry = next(e for e in entries if e["type"] == "predictions")
    derived = [{"n": c["n"], "company_id": c["company_id"], "name": c["name"], "probability": c["probability"],
                "predicted_pick": c["predicted_pick"], "recommendation": c["recommendation"]} for c in candidates]
    check("sealed predictions", pred_entry["predictions"] == derived and pred_entry["seq"] == meta["predictions_seq"],
          f"predictions committed at entry #{pred_entry['seq']}, before any human decision")
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    check("report", render_round(meta, candidates, facts) == report, "round report re-renders byte-for-byte")


def _verify_decide(run_dir, meta, entries, files_ok, check):
    ref = next(e for e in entries if e["type"] == "reference")
    scout_dir = RUNS_DIR / ref["scout_run_id"]
    scout_entries = read_ledger(scout_dir)
    pred_entry = next((e for e in scout_entries if e["seq"] == ref["predictions_seq"]), None)
    scout_sealed = json.loads((scout_dir / "head.sig").read_text(encoding="utf-8"))
    ref_ok = (pred_entry is not None and pred_entry["entry_hash"] == ref["predictions_entry_hash"]
              and scout_sealed["head_hash"] == ref["scout_head_hash"] and verify_signature(scout_sealed))
    human = next(e for e in entries if e["type"] == "human_decision")
    picked = {d["company_id"] for d in human["decisions"] if d["picked"]}
    agreement = learn.agreement(pred_entry["predictions"], picked) if pred_entry else None
    check("predictions came first", ref_ok and agreement == meta["agreement"],
          f"agreement {agreement['decisions_matched']}/{agreement['total']} recomputed against predictions sealed in "
          f"{ref['scout_run_id']} before the human decided" if ref_ok and agreement == meta["agreement"]
          else "referenced predictions are missing, altered, or the agreement score does not reproduce")
    training = json.loads((run_dir / "training_set.json").read_text(encoding="utf-8"))
    model_entry = next(e for e in entries if e["type"] == "model_state")
    rows = [{"features": {"vector": t["vector"]}, "label": t["label"]} for t in training]
    import re
    import yaml
    strategy_text = next(e for e in entries if e["type"] == "strategy")["text"]
    strategy = yaml.safe_load(re.search(r"```yaml\n(.*?)```", strategy_text, re.S).group(1))
    refit = learn.fit(rows, strategy)
    same = (sha256_hex((run_dir / "training_set.json").read_bytes()) == model_entry["training_set_hash"]
            and all(abs(refit["weights"][f] - model_entry["model"]["weights"][f]) < 1e-6 for f in refit["weights"]))
    check("learning", files_ok and same,
          f"model re-fitted from {len(training)} recorded decisions under the sealed STRATEGY.md: same weights" if files_ok and same
          else "re-fitting the recorded decisions does not give the sealed model")
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    check("report", render_decision(meta, meta["decisions"], meta["agreement"], meta["learned"]) == report,
          "decision report re-renders byte-for-byte")


def _sealed_allowed_actions(entries) -> set:
    import re
    import yaml
    strategy_entry = next((e for e in entries if e["type"] == "strategy"), None)
    if not strategy_entry:
        return set()
    rules = yaml.safe_load(re.search(r"```yaml\n(.*?)```", strategy_entry["text"], re.S).group(1))
    if sha256_hex(strategy_entry["text"].encode("utf-8")) != strategy_entry["text_hash"]:
        return set()
    return set(rules.get("actions", {}).get("allowed", [])) - set(rules.get("actions", {}).get("forbidden", []))


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
    if not seen:
        info("witness: no live API calls in this run")
        return True
    passed = not failures
    (ok if passed else bad)(
        f"witness: {len(seen)}/{len(seen)} calls confirmed by Crustdata's usage log (endpoint, request body, status, credits)"
        if passed else "witness: " + "; ".join(failures[:5]))
    if passed:
        info("note: the usage log proves each call happened with these parameters; it does not store response bodies.")
    return passed
