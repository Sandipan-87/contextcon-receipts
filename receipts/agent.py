"""The diligence agent: pitch -> claims -> resolved company -> receipts -> verdicts -> signed memo."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from rich.markup import escape

from . import trace
from .claims import CONTRADICTED, ROLE_PATTERNS, UNVERIFIABLE, evaluate
from .config import RUNS_DIR
from .extract import extract
from .facts import FactStore
from .ledger import Ledger, sha256_hex
from .proxy import CrustdataClient, ToolError
from .render import ICONS, render_report
from .resolve import resolve_company
from .pitch_policy import act_on_pitch, pitch_decision
from .strategy import load_strategy

ENRICH_FIELDS = [
    "basic_info.name", "basic_info.primary_domain", "basic_info.year_founded",
    "headcount.total", "headcount.timeseries",
    "funding.total_investment_usd", "funding.milestones",
    "revenue.estimated",
]
COMPANY = "/0/matches/0/company_data"
INPUTS_BY_TYPE = {
    "founded_year": ["year_founded"],
    "headcount": ["headcount_total", "timeseries"],
    "total_funding": ["total_investment_usd"],
    "round": ["milestones"],
    "person_role": ["company_id", "current_profile", "past_profile", "current_count", "past_count"],
    "prior_employer": ["company_id", "current_profile", "past_profile", "current_count", "past_count"],
    "hiring": ["job_count", "category_buckets"],
    "revenue": ["revenue_lower", "revenue_upper"],
    "other": [],
}
PERSON_FIELDS = ["basic_profile.name", "basic_profile.current_title",
                 "experience.employment_details.current", "experience.employment_details.past"]


def run(pitch: str, domain: str | None = None, use_cache: bool = True) -> Path:
    run_id = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(run_dir, run_id, previous_head=_latest_head(run_dir))
    trace.console.rule(f"[bold]Receipts · {run_id}")
    strategy, strategy_text = load_strategy()
    tol = strategy.get("tolerances", {})
    ledger.append("strategy", {"path": "strategy/STRATEGY.md", "text": strategy_text,
                               "text_hash": sha256_hex(strategy_text.encode("utf-8"))})

    ledger.append("input", {"pitch": pitch, "pitch_hash": sha256_hex(pitch.encode("utf-8")), "domain_hint": domain})

    trace.step("Extracting checkable claims from the pitch")
    extraction, extractor = extract(pitch)
    ledger.append("extraction", {"extractor": extractor, **extraction})
    trace.info(f"extractor: {extractor} · company: {extraction.get('company_name')!r} · founders: {extraction.get('founders')}")
    for c in extraction["claims"]:
        trace.info(escape(f"  {c['claim_id']} [{c['type']}] {c['text']}"))

    client = CrustdataClient(ledger, use_cache=use_cache)
    claimed = {c["type"]: c["params"] for c in extraction["claims"]}
    resolution = resolve_company(
        client, ledger,
        mention=extraction.get("company_name"),
        domain=domain or extraction.get("domain"),
        founders=extraction.get("founders") or [],
        sector=extraction.get("sector"),
        claimed_founded=int(claimed["founded_year"]["year"]) if claimed.get("founded_year", {}).get("year") else None,
        claimed_headcount=int(claimed["headcount"]["value"]) if claimed.get("headcount", {}).get("value") else None,
    )

    facts = FactStore()
    refs: dict[str, str | None] = {}
    unavailable: dict[str, int] = {}
    if resolution.status == "RESOLVED":
        _gather(client, facts, refs, unavailable, resolution.company_id, extraction["claims"])

    trace.step("Checking each claim (deterministic comparators)")
    results = []
    for c in extraction["claims"]:
        results.append(_check(c, resolution, facts, refs, unavailable, ledger, tol))

    decision = pitch_decision(results, resolution, strategy)
    ledger.append("decision", {"question": "What should the fund do with this pitch?", **decision})
    trace.step(f"Decision: {decision['decision']}")
    trace.info(escape(decision["rule"]))

    meta = {
        "kind": "pitch",
        "run_id": run_id,
        "decision": decision,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "extractor": extractor,
        "company_mention": extraction.get("company_name"),
        "resolution": {"status": resolution.status, "company_id": resolution.company_id, "name": resolution.name,
                       "domain": resolution.domain, "rationale": resolution.rationale,
                       "decision_seq": resolution.decision_seq, "candidates": resolution.candidates},
        "credits_spent": round(client.credits_spent, 3),
    }
    _write_json(run_dir / "meta.json", meta)
    facts.save(run_dir / "facts.json")
    _write_json(run_dir / "claims.json", results)
    ledger.append("claim_set", {
        "claims_hash": sha256_hex((run_dir / "claims.json").read_bytes()),
        "facts_hash": sha256_hex((run_dir / "facts.json").read_bytes()),
        "meta_hash": sha256_hex((run_dir / "meta.json").read_bytes()),
    })

    report = render_report(meta, results, {fid: vars(f) for fid, f in facts.facts.items()})
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    ledger.append("report", {"report_hash": sha256_hex(report.encode("utf-8"))})
    act_on_pitch(ledger, strategy, run_id, decision, resolution, results)
    sealed = ledger.seal()

    trace.step("Sealed")
    trace.ok(f"{len(ledger.entries)} ledger entries · head {sealed['head_hash'][:23]}… · Ed25519 signed")
    trace.info(f"credits spent this run: {meta['credits_spent']}")
    trace.info(f"memo: {run_dir / 'report.md'}")
    return run_dir


def _gather(client, facts, refs, unavailable, company_id, claims):
    types = {c["type"] for c in claims}
    trace.step(f"Gathering evidence for company {company_id}")

    try:
        r = client.post("/company/enrich", {"crustdata_company_ids": [company_id], "fields": ENRICH_FIELDS}, "company facts")
        for name, pointer, label in [
            ("company_id", f"{COMPANY}/crustdata_company_id", "Crustdata company ID"),
            ("year_founded", f"{COMPANY}/basic_info/year_founded", "Founding year"),
            ("headcount_total", f"{COMPANY}/headcount/total", "Headcount (total)"),
            ("timeseries", f"{COMPANY}/headcount/timeseries", "Headcount history (weekly series)"),
            ("total_investment_usd", f"{COMPANY}/funding/total_investment_usd", "Total funding (USD)"),
            ("milestones", f"{COMPANY}/funding/milestones", "Funding rounds (dated)"),
            ("revenue_lower", f"{COMPANY}/revenue/estimated/lower_bound_usd", "Modeled revenue estimate, lower bound"),
            ("revenue_upper", f"{COMPANY}/revenue/estimated/upper_bound_usd", "Modeled revenue estimate, upper bound"),
        ]:
            f = facts.add(r, pointer, label)
            refs[name] = f.id if f else None
    except ToolError as exc:
        trace.bad(f"company enrich failed: {exc}")
        for name in ["year_founded", "headcount_total", "timeseries", "total_investment_usd", "milestones", "revenue_lower", "revenue_upper"]:
            unavailable[name] = exc.seq
        refs["company_id"] = None

    if "hiring" in types:
        try:
            r = client.post("/job/search", {
                "filters": {"field": "company.basic_info.crustdata_company_id", "type": "=", "value": company_id},
                "limit": 0,
                "aggregations": [{"type": "count"},
                                 {"type": "group_by", "field": "job_details.category", "agg": "count", "size": 25}],
            }, "open roles")
            for name, pointer, label in [("job_count", "/total_count", "Open job listings (count)"),
                                         ("category_buckets", "/aggregations/1/buckets", "Open roles by category")]:
                f = facts.add(r, pointer, label)
                refs[name] = f.id if f else None
        except ToolError as exc:
            trace.bad(f"job search failed: {exc}")
            unavailable["job_count"] = unavailable["category_buckets"] = exc.seq

    people = {}
    for c in claims:
        p = c["params"] or {}
        if c["type"] in ("person_role", "prior_employer") and p.get("person") and p["person"] not in people:
            people[p["person"]] = p.get("role")
    for person, role in people.items():
        _gather_person(client, facts, refs, unavailable, company_id, person, role)


def _gather_person(client, facts, refs, unavailable, company_id, person, role):
    """Find the right person at the company. A first name alone is ambiguous (Mercury has more than one
    'Max'), so candidates holding the claimed role win; every choice is logged as a decision entry."""
    key = f"person:{person}"
    ledger = client.ledger
    role_re = ROLE_PATTERNS.get((role or "").upper()) if role else None
    first = person.split()[0].lower()

    def title_at_company(p, which="current"):
        return "; ".join(j.get("title") or "" for j in (p.get("experience", {}).get("employment_details", {}).get(which) or [])
                         if j.get("crustdata_company_id") == company_id)

    def has_role(p, which="current"):
        return bool(role_re and re.search(role_re, title_at_company(p, which).lower()))

    def first_name_match(p):
        tokens = (p.get("basic_profile", {}).get("name") or "").lower().split()
        return bool(tokens) and (tokens[0].startswith(first) or first.startswith(tokens[0]))

    def choose(receipt, index, why, candidates, which="current"):
        p = receipt.data["profiles"][index]
        f = facts.add(receipt, f"/profiles/{index}", f"Profile of {p['basic_profile']['name']} ({which} employee)")
        refs[f"{key}:{which}_profile"] = f.id
        ledger.append("decision", {
            "question": f"Which person is {person!r}" + (f" ({role})" if role else "") + "?",
            "status": "RESOLVED", "chosen": p.get("crustdata_person_id"), "rationale": why,
            "candidates": candidates, "evidence_receipts": [receipt.seq],
        })
        trace.ok(f"person {person!r} → {p['basic_profile']['name']} ({title_at_company(p, which) or which}) · {why}")

    def summary(p, which="current"):
        return {"name": p.get("basic_profile", {}).get("name"), "title_at_company": title_at_company(p, which)}

    def not_found(why, cands, receipts):
        ledger.append("decision", {"question": f"Which person is {person!r}" + (f" ({role})" if role else "") + "?",
                                   "status": "NOT_FOUND", "chosen": None, "rationale": why, "candidates": cands[:8],
                                   "evidence_receipts": receipts})
        trace.warn(f"person {person!r}: {why}")

    full_name = " " in person.strip()
    try:
        r = client.post("/person/search", {"filters": {"op": "and", "conditions": [
            {"field": "basic_profile.name", "type": "(.)", "value": person},
            {"field": "experience.employment_details.current.company_id", "type": "=", "value": company_id},
        ]}, "limit": 10, "fields": PERSON_FIELDS}, f"is {person!r} at the company now?")
        count = facts.add(r, "/total_count", f"People named {person} currently at the company")
        refs[f"{key}:current_count"] = count.id if count else None
        profiles = r.data.get("profiles") or []
        cands = [summary(p) for p in profiles]
        role_hits = [i for i, p in enumerate(profiles) if has_role(p)]
        if role_hits:
            return choose(r, role_hits[0], f"name match holding the claimed role among {len(profiles)} name matches", cands)
        if not role_re and profiles and (full_name or len(profiles) == 1):
            return choose(r, 0, "name match at the company (no role claimed)", cands)

        receipts = [r.seq]
        cands2 = list(cands)
        if role_re:
            # Short or partial names ("Max" for "Maximilian"): list the leadership, match first name + role in code.
            r2 = client.post("/person/search", {"filters": {"op": "and", "conditions": [
                {"field": "experience.employment_details.current.company_id", "type": "=", "value": company_id},
                {"field": "experience.employment_details.current.seniority_level", "type": "in",
                 "value": ["CXO", "Owner / Partner", "Vice President", "Director"]},
            ]}, "limit": 50, "fields": PERSON_FIELDS}, "current leadership")
            receipts.append(r2.seq)
            leaders = r2.data.get("profiles") or []
            hits = [i for i, p in enumerate(leaders) if first_name_match(p)]
            cands2 += [summary(leaders[i]) for i in hits]
            role_leaders = [i for i in hits if has_role(leaders[i])]
            if role_leaders:
                others = f"; {len(profiles)} other '{person}' match(es) at the company do not hold this role" if profiles else ""
                return choose(r2, role_leaders[0], f"first-name match in current leadership holding the claimed role{others}", cands2)

        # Not a current role holder: maybe they held it and left.
        r3 = client.post("/person/search", {"filters": {"op": "and", "conditions": [
            {"field": "basic_profile.name", "type": "(.)", "value": person},
            {"field": "experience.employment_details.past.company_id", "type": "=", "value": company_id},
        ]}, "limit": 10, "fields": PERSON_FIELDS}, f"did {person!r} leave the company?")
        receipts.append(r3.seq)
        count = facts.add(r3, "/total_count", f"People named {person} who previously worked at the company")
        refs[f"{key}:past_count"] = count.id if count else None
        former = r3.data.get("profiles") or []
        cands2 += [summary(p, "past") for p in former]
        if role_re:
            past_role = [i for i, p in enumerate(former) if has_role(p, "past")]
            if past_role:
                return choose(r3, past_role[0], "held the claimed role at the company in the past; no longer there", cands2, "past")
            if full_name and len(profiles) == 1:
                return choose(r, 0, "unique full-name match at the company, but in a different role", cands2)
            return not_found(f"nobody named {person!r} holds or held the {role} role at the company "
                             f"({len(profiles)} current and {len(former)} former namesakes checked)", cands2, receipts)
        if former and (full_name or len(former) == 1):
            return choose(r3, 0, "not a current employee; found among former employees", cands2, "past")
        return not_found("no unique current or former employee matches this name", cands2, receipts)
    except ToolError as exc:
        trace.bad(f"person search for {person!r} failed: {exc}")
        for suffix in ("current_profile", "past_profile", "current_count", "past_count"):
            unavailable[f"{key}:{suffix}"] = exc.seq


def _check(c, resolution, facts, refs, unavailable, ledger, tol) -> dict:
    record = {"claim_id": c["claim_id"], "type": c["type"], "text": c["text"], "params": c["params"], "inputs": {}, "tol": tol}
    if resolution.status != "RESOLVED":
        record.update(status=UNVERIFIABLE, unavailable_seq=resolution.decision_seq,
                      explanation=f"The company could not be resolved ({resolution.status}), so nothing was checked.")
        return _log(record)

    names = INPUTS_BY_TYPE.get(c["type"], [])
    person = (c["params"] or {}).get("person")
    inputs, local_refs = {}, {}
    for name in names:
        key = f"person:{person}:{name}" if name in ("current_profile", "past_profile", "current_count", "past_count") else name
        if key in unavailable:
            record.update(status=UNVERIFIABLE, unavailable_seq=unavailable[key],
                          explanation=f"Data unavailable: the Crustdata call failed (ledger entry #{unavailable[key]}).")
            return _log(record)
        fid = refs.get(key)
        record["inputs"][name] = fid
        local_refs[name] = fid
        inputs[name] = facts.value(fid) if fid else None

    status, explanation = evaluate(c["type"], c["params"], inputs, local_refs, tol)
    record.update(status=status, explanation=explanation)
    if c["type"] == "headcount" and status == UNVERIFIABLE and "unstable" in explanation:
        ledger.append("anomaly", {"claim_id": c["claim_id"], "kind": "unstable_headcount_series",
                                  "detail": explanation, "facts": [local_refs.get("headcount_total"), local_refs.get("timeseries")]})
    return _log(record)


def _log(record):
    style = "red" if record["status"] == CONTRADICTED else "green" if record["status"] == "VERIFIED" else "yellow"
    trace.console.print(f"  {ICONS[record['status']]} [{style}]{record['status']:<12}[/] {record['claim_id']} {escape(record['explanation'])}")
    return record


def _latest_head(current_dir: Path) -> str | None:
    heads = sorted((p for p in RUNS_DIR.glob("*/head.sig") if p.parent != current_dir), key=lambda p: p.stat().st_mtime)
    if not heads:
        return None
    return json.loads(heads[-1].read_text(encoding="utf-8")).get("head_hash")


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")

