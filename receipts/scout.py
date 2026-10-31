"""Scouting round: thesis search -> receipt-backed features -> learned scoring -> sealed predictions
-> autonomous actions within STRATEGY.md limits (everything else is queued for the human)."""

import json
from datetime import datetime, timezone

from . import board, learn, trace
from .actions import ActionRunner
from .compose import draft
from .config import ROOT, RUNS_DIR
from .facts import FactStore
from .features import compute, reason, thesis_violations
from .ledger import Ledger, sha256_hex
from .proxy import CrustdataClient, ToolError

MODEL_PATH = ROOT / "data" / "model.json"
ENRICH_FIELDS = ["basic_info.name", "basic_info.primary_domain", "basic_info.year_founded", "headcount.total",
                 "headcount.growth_percent", "headcount.timeseries", "funding.total_investment_usd",
                 "funding.last_round_type", "funding.last_fundraise_date"]


def current_model(strategy: dict) -> dict:
    """The latest model fitted from human decisions, or the stated-thesis prior if none yet."""
    if MODEL_PATH.exists():
        model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
        if model.get("strategy_hash") == sha256_hex(json.dumps(strategy, sort_keys=True).encode()):
            return model
        trace.warn("STRATEGY.md changed since the model was fitted; re-fitting on recorded decisions")
    conn = board.connect()
    rows = board.training_rows(conn)
    return {**learn.fit(rows, strategy), "fitted_in_run": None,
            "strategy_hash": sha256_hex(json.dumps(strategy, sort_keys=True).encode())}


def new_run(kind: str) -> tuple[str, "Ledger"]:
    run_id = datetime.now(timezone.utc).strftime(f"{kind}_%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    heads = sorted(RUNS_DIR.glob("*/head.sig"), key=lambda p: p.stat().st_mtime)
    prev = json.loads(heads[-1].read_text(encoding="utf-8"))["head_hash"] if heads else None
    return run_id, Ledger(run_dir, run_id, previous_head=prev)


def scout(strategy: dict, strategy_text: str, n: int = 10, round_no: int | None = None, thesis_text: str | None = None) -> str:
    conn = board.connect()
    if round_no is None:
        row = conn.execute("SELECT MAX(round_no) AS r FROM deals WHERE source = 'scout'").fetchone()
        round_no = (row["r"] or 0) + 1
    run_id, ledger = new_run("scout")
    run_dir = ledger.run_dir
    as_of = datetime.now(timezone.utc).date().isoformat()
    trace.console.rule(f"[bold]Receipts scout · round {round_no} · {run_id}")

    ledger.append("strategy", {"path": "strategy/STRATEGY.md", "text": strategy_text,
                               "text_hash": sha256_hex(strategy_text.encode("utf-8"))})
    model = current_model(strategy)
    ledger.append("model_state", {"model": model, "model_hash": sha256_hex(json.dumps(model, sort_keys=True).encode())})
    trace.info(f"model: {model['n_decisions']} past decisions "
               f"({'stated thesis only' if not model['n_decisions'] else 'learned from your picks'})")

    client = CrustdataClient(ledger)
    facts = FactStore()
    thesis_request = None
    if thesis_text and thesis_text.strip():
        from .thesis import interpret
        interp = interpret(thesis_text, client, strategy["thesis"])
        strategy = {**strategy, "thesis": interp["thesis"]}
        thesis_request = {"text": interp["text"], "model": interp["model"], "unmapped": interp["mapping"]["unmapped"],
                          "notes": interp["mapping"]["notes"], "industries": interp["mapping"]["industries"]}
        ledger.append("thesis_request", {**thesis_request, "proposed": interp["mapping"]["proposed"], "filters": interp["thesis"]})
    thesis = strategy["thesis"]

    trace.step(f"Scouting {n} new companies matching the thesis")
    seen = board.seen_company_ids(conn)
    relaxed = []
    for attempt, (variant, note) in enumerate(relaxations(thesis)):
        if note:
            relaxed.append(note)
            trace.warn(f"too few new matches; relaxing: {note}")
            ledger.append("decision", {"question": "Too few new companies match; relax the search?", "status": "RELAXED",
                                       "chosen": note, "rationale": "fewer new matches than requested; relax the least essential filter first",
                                       "candidates": [], "evidence_receipts": [search.seq]})
        search = client.post("/company/search", {
            "filters": {"op": "and", "conditions": search_conditions(variant)},
            "sorts": [{"field": "funding.last_fundraise_date", "order": "desc"}],
            "limit": min(100, n + len(seen) + 5),
            "fields": ["crustdata_company_id", "basic_info.name", "basic_info.primary_domain", "locations.country"],
        }, "thesis search" if not note else f"search, relaxed: {note}")
        new = [c for c in search.data.get("companies", []) if c["crustdata_company_id"] not in seen]
        if len(new) >= min(n, 3):
            break
    thesis = variant
    strategy = {**strategy, "thesis": thesis}  # the relaxed thesis is the one in force (recorded in meta)
    picked = []
    for i, c in enumerate(search.data.get("companies", [])):
        if c["crustdata_company_id"] not in seen and len(picked) < n:
            picked.append((i, c))
    trace.info(f"{search.data.get('total_count')} companies match the thesis; {len(picked)} new ones selected "
               f"({len(seen)} already on the deal board skipped)")
    if not picked:
        raise SystemExit(f"No new companies match these filters ({search.data.get('total_count')} total, all already on the board "
                         "or none at all). Try a broader thesis: fewer keywords, more countries or rounds.")

    ids = [c["crustdata_company_id"] for _, c in picked]
    trace.step("Gathering receipt-backed facts")
    enrich = client.post("/company/enrich", {"crustdata_company_ids": ids, "fields": ENRICH_FIELDS}, f"facts for {len(ids)} companies")
    jobs = eng = None
    try:
        jobs = client.post("/job/search", {"filters": {"field": "company.basic_info.crustdata_company_id", "type": "in", "value": ids},
                                           "limit": 0, "aggregations": [{"type": "group_by", "field": "company.basic_info.crustdata_company_id",
                                                                          "agg": "count", "size": 100}]}, "open roles per company")
        eng = client.post("/job/search", {"filters": {"op": "and", "conditions": [
            {"field": "company.basic_info.crustdata_company_id", "type": "in", "value": ids},
            {"field": "job_details.category", "type": "=", "value": "Engineering"}]},
            "limit": 0, "aggregations": [{"type": "group_by", "field": "company.basic_info.crustdata_company_id",
                                          "agg": "count", "size": 100}]}, "engineering roles per company")
    except ToolError as exc:
        trace.bad(f"job search failed; hiring features will be missing: {exc}")
    job_fact = facts.add(jobs, "/aggregations/0/buckets", "Open roles per company") if jobs else None
    eng_fact = facts.add(eng, "/aggregations/0/buckets", "Engineering roles per company") if eng else None

    by_id = {}
    for idx, item in enumerate(enrich.data):
        matches = item.get("matches") or []
        if matches:
            by_id[matches[0]["company_data"]["crustdata_company_id"]] = idx

    trace.step("Scoring against your strategy and learned preferences")
    thresholds = strategy["decision_thresholds"]
    autonomy = strategy["autonomy"]
    candidates = []
    for rank, (search_idx, c) in enumerate(picked, start=1):
        cid = c["crustdata_company_id"]
        idx = by_id.get(cid)
        refs = {"job_buckets": job_fact.id if job_fact else None, "eng_buckets": eng_fact.id if eng_fact else None}
        country_fact = facts.add(search, f"/companies/{search_idx}/locations/country", "HQ country")
        refs["country"] = country_fact.id if country_fact else None
        if idx is not None:
            base = f"/{idx}/matches/0/company_data"
            for name, pointer, label in [
                ("company_id", f"{base}/crustdata_company_id", "Crustdata company ID"),
                ("name", f"{base}/basic_info/name", "Company name"),
                ("domain", f"{base}/basic_info/primary_domain", "Domain"),
                ("year_founded", f"{base}/basic_info/year_founded", "Founding year"),
                ("headcount_total", f"{base}/headcount/total", "Headcount"),
                ("growth_yoy", f"{base}/headcount/growth_percent/yoy", "Headcount growth, year on year (%)"),
                ("timeseries", f"{base}/headcount/timeseries", "Headcount history"),
                ("total_funding", f"{base}/funding/total_investment_usd", "Total funding (USD)"),
                ("last_round_type", f"{base}/funding/last_round_type", "Last round type"),
                ("last_fundraise_date", f"{base}/funding/last_fundraise_date", "Last fundraise date"),
            ]:
                f = facts.add(enrich, pointer, label)
                refs[name] = f.id if f else None
        values = {k: (facts.value(fid) if fid else None) for k, fid in refs.items()}
        values["company_id"] = cid
        feats = compute(values, as_of)
        pred = learn.predict(model, feats["vector"])
        name = values.get("name") or c["basic_info"]["name"]
        domain = values.get("domain") or c["basic_info"].get("primary_domain")

        violations = thesis_violations(feats["raw"], values.get("country"), strategy)
        if idx is None:
            rec, rule, auto = "NEEDS_HUMAN", "no enrichment data returned; cannot judge", False
        elif violations:
            rec, rule, auto = "PASS", "hard thesis filter: " + "; ".join(violations), True
        elif len(feats["missing"]) >= 4:
            rec, rule, auto = "NEEDS_HUMAN", f"too little data ({', '.join(feats['missing'])} missing)", False
        else:
            p = pred["probability"]
            if p >= thresholds["advance_at_or_above"]:
                rec, rule = "ADVANCE", f"p(pick) {p:.2f} ≥ decision_thresholds.advance_at_or_above {thresholds['advance_at_or_above']}"
            elif p <= thresholds["pass_at_or_below"]:
                rec, rule = "PASS", f"p(pick) {p:.2f} ≤ decision_thresholds.pass_at_or_below {thresholds['pass_at_or_below']}"
            else:
                rec, rule = "NEEDS_HUMAN", f"p(pick) {p:.2f} between thresholds"
            auto = (rec != "NEEDS_HUMAN" and pred["confidence"] >= autonomy["auto_act_if_confidence"]
                    and model["n_decisions"] >= autonomy["min_decisions_before_auto_act"])
        why = [reason(f, feats["vector"][f], v) for f, v in pred["contributions"][:3] if abs(v) >= 0.05]
        candidates.append({
            "n": rank, "company_id": cid, "name": name, "domain": domain, "refs": refs, "raw": feats["raw"],
            "vector": feats["vector"], "missing": feats["missing"], "probability": pred["probability"],
            "confidence": pred["confidence"], "contributions": pred["contributions"], "why": why,
            "recommendation": rec, "rule": rule, "auto_act": auto, "predicted_pick": False,
        })
        icon = {"ADVANCE": "🟢", "PASS": "🔴", "NEEDS_HUMAN": "🟡"}[rec]
        trace.info(f"{icon} {rank:>2}. {name} · p(pick) {pred['probability']:.2f} · {rec}"
                   f"{' (auto)' if auto else ' (queued for you)'} · {', '.join(why) or 'no strong signal'}")

    k = predicted_pick_count(model, strategy, len(candidates))
    for c in sorted(candidates, key=lambda c: (-c["probability"], c["n"]))[:k]:
        c["predicted_pick"] = True
    trace.info(f"agent predicts you will pick {k} of {len(candidates)} (pick rate "
               f"{'from your history' if model['n_decisions'] else 'assumed by STRATEGY.md'}): "
               + ", ".join(str(c["n"]) for c in candidates if c["predicted_pick"]))

    predictions = [{"n": c["n"], "company_id": c["company_id"], "name": c["name"], "probability": c["probability"],
                    "predicted_pick": c["predicted_pick"], "recommendation": c["recommendation"]} for c in candidates]
    commit = ledger.append("predictions", {"round_no": round_no, "predictions": predictions,
                                           "predictions_hash": sha256_hex(json.dumps(predictions, sort_keys=True).encode())})
    trace.ok(f"predictions committed to the ledger (entry #{commit['seq']}) before any human decision")

    trace.step("Acting within the rulebook")
    runner = ActionRunner(ledger, strategy, run_id)
    for c in candidates:
        if c["auto_act"]:
            stage = {"ADVANCE": "Partner meeting", "PASS": "Passed"}[c["recommendation"]]
            because = f"autonomous: {c['rule']}; confidence {c['confidence']:.2f}"
        else:
            stage = "Needs analyst"
            because = (f"queued: recommendation {c['recommendation']} ({c['rule']}); autonomy requires confidence ≥ "
                       f"{autonomy['auto_act_if_confidence']} and ≥ {autonomy['min_decisions_before_auto_act']} past decisions "
                       f"(have {model['n_decisions']})")
        runner.update_board(c["company_id"], because, name=c["name"], domain=c["domain"], source="scout", round_no=round_no,
                            stage=stage, agent_recommendation=c["recommendation"], agent_probability=c["probability"],
                            agent_confidence=c["confidence"], features={"raw": c["raw"], "vector": c["vector"]})
        if c["auto_act"] and c["recommendation"] == "ADVANCE":
            intro_email(runner, c, because)

    meta = {"kind": "scout", "run_id": run_id, "round_no": round_no, "as_of": as_of, "model": model,
            "thesis": thesis, "thesis_request": thesis_request, "relaxed": relaxed,
            "strategy_hash": sha256_hex(strategy_text.encode("utf-8")), "credits_spent": round(client.credits_spent, 3),
            "predictions_seq": commit["seq"]}
    _write(run_dir / "meta.json", meta)
    _write(run_dir / "round.json", candidates)
    facts.save(run_dir / "facts.json")
    ledger.append("claim_set", {"round_hash": sha256_hex((run_dir / "round.json").read_bytes()),
                                "facts_hash": sha256_hex((run_dir / "facts.json").read_bytes()),
                                "meta_hash": sha256_hex((run_dir / "meta.json").read_bytes())})
    from .render import render_round
    report = render_round(meta, candidates, {fid: vars(f) for fid, f in facts.facts.items()})
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    ledger.append("report", {"report_hash": sha256_hex(report.encode("utf-8"))})
    sealed = ledger.seal()
    trace.step("Sealed")
    trace.ok(f"head {sealed['head_hash'][:23]}… · Ed25519 signed · credits {meta['credits_spent']}")
    trace.info(f"round report: {run_dir / 'report.md'}")
    trace.info(f"now decide:  python -m receipts decide --round {round_no} --pick 1,4,7   (numbers from the table)")
    return run_id


def search_conditions(thesis: dict) -> list[dict]:
    return [
        {"field": "taxonomy.professional_network_industry", "type": "in", "value": thesis["sectors"]},
        {"field": "locations.country", "type": "in", "value": thesis["hq_countries"]},
        {"field": "headcount.total", "type": "=>", "value": thesis["headcount"][0]},
        {"field": "headcount.total", "type": "=<", "value": thesis["headcount"][1]},
        {"field": "funding.last_round_type", "type": "in", "value": thesis["last_round"]},
        *([{"field": "funding.last_fundraise_date", "type": "=>", "value": thesis["raised_since"]}] if thesis.get("raised_since") else []),
        *([{"op": "or", "conditions": [{"field": "basic_info.description", "type": "(.)", "value": k}
                                       for k in thesis["description_keywords"]]}] if thesis.get("description_keywords") else []),
    ]


def relaxations(thesis: dict):
    """The exact thesis first, then progressively looser versions (least essential filter first).
    Industry, country and the rulebook's headcount range are never relaxed."""
    yield thesis, None
    current = dict(thesis)
    keywords = current.get("description_keywords") or []
    words = [w for k in keywords for w in k.split() if len(w) >= 4]
    if keywords and words and words != keywords:
        current = {**current, "description_keywords": words}
        yield current, f"description keywords split into single words ({', '.join(words)})"
    if current.get("description_keywords"):
        current = {k: v for k, v in current.items() if k != "description_keywords"}
        yield current, "dropped the description-keyword filter"
    if current.get("raised_since"):
        current = {k: v for k, v in current.items() if k != "raised_since"}
        yield current, "dropped the 'raised since' recency filter"
    neighbours = {"seed": ["pre_seed", "series_a"], "series_a": ["seed", "series_b"], "series_b": ["series_a", "series_c"]}
    widened = sorted(set(current["last_round"]) | {r for x in current["last_round"] for r in neighbours.get(x, [])})
    if widened != sorted(current["last_round"]):
        current = {**current, "last_round": widened}
        yield current, f"widened rounds to neighbouring stages ({', '.join(widened)})"


def predicted_pick_count(model: dict, strategy: dict, n: int) -> int:
    rate = (model["n_picks"] / model["n_decisions"]) if model["n_decisions"] else         float(strategy.get("learning", {}).get("expected_pick_rate", 0.5))
    return max(1, min(n, round(rate * n)))


def intro_email(runner: ActionRunner, c: dict, because: str) -> None:
    raw = c["raw"]
    facts_lines = [f"Company: {c['name']} ({c['domain']})"]
    if raw.get("headcount"):
        facts_lines.append(f"Team size: {raw['headcount']:,} people")
    if raw.get("growth_yoy") is not None:
        facts_lines.append(f"Headcount growth year on year: {raw['growth_yoy']:+.0f}%")
    if raw.get("last_round_type"):
        facts_lines.append(f"Last round: {raw['last_round_type'].replace('_', ' ').title()} ({raw.get('last_fundraise_date')})")
    if raw.get("open_roles"):
        facts_lines.append(f"Open roles: {raw['open_roles']} ({raw.get('eng_roles', 0)} in engineering)")
    template = (f"Hi {c['name']} team,\n\nWe have been following {c['name']}'s progress and would love to learn more. "
                f"{' '.join(line + '.' for line in facts_lines[1:])}\n\nWould you be open to a 30-minute call with our partners "
                f"in the next two weeks?\n\nBest,\n[Analyst name]")
    body, author = draft("intro / partner-meeting request to the founders", c["name"], facts_lines, template)
    runner.draft_email(c["company_id"], c["name"], f"Intro: {c['name']} x our fund", body, because, author, facts_lines)


def _write(path, obj):
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
