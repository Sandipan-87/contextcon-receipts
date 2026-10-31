"""Human decisions for a scouting round: commit-then-reveal scoring, learning, and actions.

The agent's predictions were sealed in the scout run before the human chose. Here the human's picks
are recorded, the sealed predictions are checked (signature + chain) and scored against them, the
preference model is re-fitted on every recorded decision, and the resulting actions are executed.
"""

import json

from . import board, learn, trace
from .actions import ActionRunner
from .config import ROOT, RUNS_DIR
from .ledger import entry_hash, read_ledger, sha256_hex, verify_signature
from .scout import MODEL_PATH, intro_email, new_run

LEARNED_PATH = ROOT / "strategy" / "LEARNED.md"


def find_scout_run(round_no: int):
    runs = []
    for meta_path in RUNS_DIR.glob("scout_*/meta.json"):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("round_no") == round_no:
            runs.append(meta_path.parent)
    if not runs:
        raise SystemExit(f"no scouting run found for round {round_no}")
    return sorted(runs)[-1]


def sealed_predictions(scout_dir) -> tuple[list[dict], dict, dict]:
    """Return predictions only if the scout run's chain and signature are intact."""
    entries = read_ledger(scout_dir)
    prev = sha256_hex(entries[0]["run_id"].encode("utf-8"))
    for i, e in enumerate(entries):
        if e["seq"] != i or e["prev_hash"] != prev or entry_hash(e) != e["entry_hash"]:
            raise SystemExit(f"scout run {scout_dir.name} has been altered at entry #{i}; refusing to use its predictions")
        prev = e["entry_hash"]
    sealed = json.loads((scout_dir / "head.sig").read_text(encoding="utf-8"))
    if not verify_signature(sealed) or sealed["head_hash"] != entries[-1]["entry_hash"]:
        raise SystemExit(f"scout run {scout_dir.name} signature is invalid; refusing to use its predictions")
    entry = next(e for e in entries if e["type"] == "predictions")
    return entry["predictions"], entry, sealed


def parse_picks(spec: str, predictions: list[dict]) -> set[int]:
    picked = set()
    for token in [t.strip() for t in spec.split(",") if t.strip()]:
        if token.isdigit():
            match = [p for p in predictions if p["n"] == int(token)]
        else:
            match = [p for p in predictions if token.lower() in p["name"].lower()]
        if len(match) != 1:
            raise SystemExit(f"pick {token!r} matches {len(match)} companies in this round; use the table number")
        picked.add(match[0]["company_id"])
    return picked


def decide(strategy: dict, strategy_text: str, round_no: int, picks_spec: str) -> str:
    scout_dir = find_scout_run(round_no)
    predictions, pred_entry, scout_seal = sealed_predictions(scout_dir)
    picked_ids = parse_picks(picks_spec, predictions)
    candidates = {c["company_id"]: c for c in json.loads((scout_dir / "round.json").read_text(encoding="utf-8"))}

    run_id, ledger = new_run("decide")
    trace.console.rule(f"[bold]Receipts decide · round {round_no} · {run_id}")
    ledger.append("strategy", {"path": "strategy/STRATEGY.md", "text": strategy_text,
                               "text_hash": sha256_hex(strategy_text.encode("utf-8"))})
    ledger.append("reference", {"scout_run_id": scout_dir.name, "scout_head_hash": scout_seal["head_hash"],
                                "predictions_seq": pred_entry["seq"], "predictions_entry_hash": pred_entry["entry_hash"]})
    trace.ok(f"sealed predictions from {scout_dir.name} verified (signature and chain intact)")

    decisions = [{"n": p["n"], "company_id": p["company_id"], "name": p["name"], "picked": p["company_id"] in picked_ids,
                  "predicted_pick": p["predicted_pick"], "probability": p["probability"]} for p in predictions]
    ledger.append("human_decision", {"round_no": round_no, "picks_spec": picks_spec, "decided_by": "human",
                                     "decisions": [{k: d[k] for k in ("company_id", "name", "picked")} for d in decisions]})

    agreement = learn.agreement(predictions, picked_ids)
    ledger.append("agreement", {"round_no": round_no, **agreement})
    trace.step("Agent vs you (scored against the sealed predictions)")
    for d in decisions:
        mark = "[green]✔[/]" if d["predicted_pick"] == d["picked"] else "[red]✗[/]"
        trace.info(f"{mark} {d['n']:>2}. {d['name']}: agent predicted {'pick' if d['predicted_pick'] else 'reject'}"
                   f" (p {d['probability']:.2f}), you {'PICKED' if d['picked'] else 'rejected'}")
    trace.ok(f"agreement {agreement['decisions_matched']}/{agreement['total']}; "
             f"you picked {agreement['top_k_overlap']} of the agent's top {agreement['top_k']}")

    trace.step("Executing your decisions")
    runner = ActionRunner(ledger, strategy, run_id)
    for d in decisions:
        c = candidates[d["company_id"]]
        stage = "Partner meeting" if d["picked"] else "Passed"
        because = f"human decision in round {round_no}: {'pick' if d['picked'] else 'reject'}"
        runner.update_board(d["company_id"], because, name=d["name"], stage=stage,
                            human_decision="pick" if d["picked"] else "reject",
                            features={"raw": c["raw"], "vector": c["vector"]})
        if d["picked"]:
            intro_email(runner, c, because)

    trace.step("Learning your preferences")
    rows = board.training_rows(board.connect())
    model = learn.fit(rows, strategy)
    model.update({"fitted_in_run": run_id, "strategy_hash": sha256_hex(json.dumps(strategy, sort_keys=True).encode())})
    training_set = [{"company_id": r["company_id"], "label": r["label"], "vector": r["features"]["vector"]} for r in rows]
    _write(ledger.run_dir / "training_set.json", training_set)
    ledger.append("model_state", {"model": model, "training_set_hash": sha256_hex((ledger.run_dir / "training_set.json").read_bytes()),
                                  "model_hash": sha256_hex(json.dumps(model, sort_keys=True).encode())})
    learned = learn.learned_summary(strategy, model, rows)
    ledger.append("learned", {"summary": learned})
    for line in learned:
        trace.info(f"• {line}")
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_text(json.dumps(model, indent=1), encoding="utf-8")

    meta = {"kind": "decide", "run_id": run_id, "round_no": round_no, "scout_run_id": scout_dir.name,
            "scout_head_hash": scout_seal["head_hash"], "agreement": agreement, "model_after": model,
            "prior_weights": strategy["learning"]["prior_weights"], "decisions": decisions, "learned": learned}
    _write(ledger.run_dir / "meta.json", meta)
    ledger.append("claim_set", {"meta_hash": sha256_hex((ledger.run_dir / "meta.json").read_bytes())})
    from .render import render_decision
    report = render_decision(meta, decisions, agreement, learned)
    (ledger.run_dir / "report.md").write_text(report, encoding="utf-8")
    ledger.append("report", {"report_hash": sha256_hex(report.encode("utf-8"))})
    _update_learned_md(meta, report)
    sealed = ledger.seal()
    trace.ok(f"sealed {run_id} · head {sealed['head_hash'][:23]}…")
    return run_id


def _update_learned_md(meta: dict, report: str) -> None:
    history_path = ROOT / "data" / "agreement_history.json"
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    history = [h for h in history if h["round_no"] != meta["round_no"]] + [{"round_no": meta["round_no"], "run_id": meta["run_id"], **meta["agreement"]}]
    history_path.write_text(json.dumps(history, indent=1), encoding="utf-8")
    lines = ["# What the agent has learned about your preferences", "",
             "Generated from the signed decision runs; edit STRATEGY.md, not this file.", "",
             "## Agreement with you, round by round (scored against sealed predictions)", "",
             "| Round | Matched decisions | Your picks among agent's top-k |", "|---|---|---|"]
    for h in history:
        lines.append(f"| {h['round_no']} | {h['decisions_matched']}/{h['total']} | {h['top_k_overlap']}/{h['top_k']} |")
    lines += ["", "## Current preferences", ""] + [f"- {line}" for line in meta["learned"]] + [""]
    LEARNED_PATH.write_text("\n".join(lines), encoding="utf-8")


def _write(path, obj):
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
