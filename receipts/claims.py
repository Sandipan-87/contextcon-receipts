"""Deterministic claim comparators.

Each comparator is a pure function of (claim params, cited fact values) -> (status, explanation).
The verifier re-runs them on the values re-resolved from the raw blobs, so a verdict can be
reproduced by anyone without trusting the agent or an LLM. Explanations cite facts as [F12].
"""

import re
from datetime import date

VERIFIED, PARTIAL, CONTRADICTED, UNSUPPORTED, UNVERIFIABLE = "VERIFIED", "PARTIAL", "CONTRADICTED", "UNSUPPORTED", "UNVERIFIABLE"
STATUS_ORDER = [CONTRADICTED, UNSUPPORTED, UNVERIFIABLE, PARTIAL, VERIFIED]

ROLE_PATTERNS = {
    "CEO": r"chief executive|\bceo\b",
    "CTO": r"chief technology|\bcto\b",
    "COO": r"chief operating|\bcoo\b",
    "CFO": r"chief financial|\bcfo\b",
    "CPO": r"chief product|\bcpo\b",
    "CMO": r"chief marketing|\bcmo\b",
    "FOUNDER": r"founder",
    "CO-FOUNDER": r"founder",
    "COFOUNDER": r"founder",
}


DEFAULT_TOLERANCES = {
    "headcount": {"verified": 15, "partial": 40},
    "total_funding": {"verified": 10, "partial": 30},
    "round_amount": 5,
    "open_roles": {"verified": 25, "partial": 50},
    "unstable_series_swing": 40,
    "total_vs_series": 15,
}


def evaluate(claim_type: str, params: dict, inputs: dict, refs: dict, tol: dict | None = None) -> tuple[str, str]:
    """inputs: name -> fact value (or None); refs: name -> fact id (or None) for citations;
    tol: the ± margins from strategy/STRATEGY.md (recorded with each claim so verify reproduces them)."""
    fn = COMPARATORS.get(claim_type, _other)
    return fn(params, inputs, refs, {**DEFAULT_TOLERANCES, **(tol or {})})


# ---------------------------------------------------------------- comparators

def _founded_year(p, x, r, t):
    actual = x.get("year_founded")
    if actual is None:
        return UNVERIFIABLE, "Crustdata has no founding year for this company."
    claimed = int(p["year"])
    if claimed == actual:
        return VERIFIED, f"Founding year {actual} {cite(r, 'year_founded')}."
    if abs(claimed - actual) == 1:
        return PARTIAL, f"Recorded founding year is {actual} {cite(r, 'year_founded')}, one year from the claim."
    return CONTRADICTED, f"Recorded founding year is {actual} {cite(r, 'year_founded')}, not {claimed}."


def _headcount(p, x, r, t):
    total = x.get("headcount_total")
    if total is None:
        return UNVERIFIABLE, "Crustdata has no headcount for this company."
    claimed = p["value"]
    if x.get("regions"):
        from .features import identity_collision
        merged = identity_collision(x["regions"], total)
        if merged:
            return UNVERIFIABLE, f"Crustdata's record looks unreliable, so the claim cannot be judged: {merged} {cite(r, 'regions')}."
    stable, why = headcount_stability(total, x.get("timeseries"), t["unstable_series_swing"], t["total_vs_series"])
    if not stable:
        return UNVERIFIABLE, (f"Crustdata headcount data is unstable, so the claim cannot be judged: {why} "
                              f"{cite(r, 'headcount_total')} {cite(r, 'timeseries')}.")
    diff = pct(claimed, total)
    if abs(diff) <= t["headcount"]["verified"]:
        return VERIFIED, f"Recorded headcount is {fmt_int(total)} {cite(r, 'headcount_total')}, within {t['headcount']['verified']}% of the claim."
    if abs(diff) <= t["headcount"]["partial"]:
        return PARTIAL, f"Recorded headcount is {fmt_int(total)} {cite(r, 'headcount_total')}; the claim is {fmt_pct(diff)} off."
    return CONTRADICTED, f"Recorded headcount is {fmt_int(total)} {cite(r, 'headcount_total')}; the claim of {fmt_int(claimed)} is {fmt_pct(diff)} off."


def _total_funding(p, x, r, t):
    total = x.get("total_investment_usd")
    if not total:
        return UNVERIFIABLE, "Crustdata has no total funding figure for this company."
    diff = pct(p["amount_usd"], total)
    if abs(diff) <= t["total_funding"]["verified"]:
        return VERIFIED, f"Total funding recorded is {fmt_usd(total)} {cite(r, 'total_investment_usd')}."
    if abs(diff) <= t["total_funding"]["partial"]:
        return PARTIAL, f"Total funding recorded is {fmt_usd(total)} {cite(r, 'total_investment_usd')}; the claim is {fmt_pct(diff)} off."
    return CONTRADICTED, f"Total funding recorded is {fmt_usd(total)} {cite(r, 'total_investment_usd')}; the claim is {fmt_pct(diff)} off."


def _round(p, x, r, t):
    milestones = x.get("milestones") or []
    if not milestones:
        return UNVERIFIABLE, "Crustdata has no funding-round history for this company."
    rtype, amount, lead = p.get("round_type"), p.get("amount_usd"), p.get("lead_investor")
    match = None
    if rtype:
        match = next((m for m in milestones if (m.get("round_type") or "").lower() == rtype), None)
    if match is None and amount:
        match = next((m for m in milestones if m.get("amount_usd") and abs(pct(amount, m["amount_usd"])) <= t["round_amount"]), None)
    if match is None:
        recorded = ", ".join(f"{label_round(m.get('round_type'))} {m.get('date') or '?'}" for m in milestones[:4])
        return CONTRADICTED, f"No {label_round(rtype) if rtype else 'matching'} round in the recorded funding history ({recorded}) {cite(r, 'milestones')}."

    desc = f"{label_round(match.get('round_type'))} on {match.get('date')}"
    problems = []
    if amount and match.get("amount_usd") and abs(pct(amount, match["amount_usd"])) > t["round_amount"]:
        problems.append(f"recorded amount is {fmt_usd(match['amount_usd'])}, not {fmt_usd(amount)}")
    lead_note = ""
    if lead:
        leads = [s.strip() for s in (match.get("lead_investors") or "").split(",") if s.strip()]
        if not leads:
            lead_note = "lead investor not recorded"
        elif not any(same_org(lead, l) for l in leads):
            problems.append(f"recorded lead investor is {', '.join(leads)}, not {lead}")
    if problems:
        return CONTRADICTED, f"{desc} {cite(r, 'milestones')}: " + "; ".join(problems) + "."
    if lead_note:
        return PARTIAL, f"{desc} {cite(r, 'milestones')} matches, but the {lead_note}."
    amount_txt = f" of {fmt_usd(match['amount_usd'])}" if match.get("amount_usd") else ""
    lead_txt = f" led by {match.get('lead_investors')}" if lead else ""
    return VERIFIED, f"{desc}{amount_txt}{lead_txt} {cite(r, 'milestones')}."


def _person_role(p, x, r, t):
    person, role = p["person"], (p.get("role") or "").upper()
    current, past = x.get("current_profile"), x.get("past_profile")
    if current:
        titles = [j.get("title") or "" for j in employment(current, "current") if j.get("crustdata_company_id") == x.get("company_id")]
        name = current.get("basic_profile", {}).get("name")
        title_txt = "; ".join(titles) or "unknown title"
        if any(re.search(ROLE_PATTERNS.get(role, re.escape(role.lower())), t.lower()) for t in titles):
            return VERIFIED, f"{name} is currently {title_txt} at the company {cite(r, 'current_profile')}."
        return PARTIAL, f"{name} currently works at the company as {title_txt}, not as {role} {cite(r, 'current_profile')}."
    if past:
        name = past.get("basic_profile", {}).get("name")
        ends = [j.get("end_date", "")[:10] for j in employment(past, "past") if j.get("crustdata_company_id") == x.get("company_id")]
        return CONTRADICTED, f"{name} is no longer at the company; their role there ended {', '.join(e for e in ends if e) or 'on an unrecorded date'} {cite(r, 'past_profile')}."
    role_txt = f" holding the {role} role" if role else ""
    return UNSUPPORTED, f"No current or former employee named {person}{role_txt} found at the company {cite(r, 'current_count')} {cite(r, 'past_count')}."


def _prior_employer(p, x, r, t):
    person, company = p["person"], p["company"]
    profile = x.get("current_profile") or x.get("past_profile")
    if not profile:
        role_txt = f" as {p['role']}" if p.get("role") else ""
        return UNVERIFIABLE, (f"No current or former employee named {person}{role_txt} was found at the company, "
                              f"so their history cannot be checked {cite(r, 'current_count')} {cite(r, 'past_count')}.")
    name = profile.get("basic_profile", {}).get("name")
    ref = "current_profile" if x.get("current_profile") else "past_profile"
    history = employment(profile, "past") + [j for j in employment(profile, "current") if j.get("crustdata_company_id") != x.get("company_id")]
    hits = [j for j in history if same_org(company, j.get("name") or "")]
    if not hits:
        employers = []
        for j in history:
            if j.get("name") and j["name"] not in employers:
                employers.append(j["name"])
        listed = ", ".join(employers[:5]) or "none recorded"
        return UNSUPPORTED, f"{name}'s recorded history has no {company} role (employers on record: {listed}) {cite(r, ref)}."
    job = hits[0]
    years = tenure_years(job.get("start_date"), job.get("end_date"))
    span = f"{(job.get('start_date') or '?')[:7]} to {(job.get('end_date') or 'present')[:7]}"
    if ref == "past_profile":
        ended = [j.get("end_date", "")[:7] for j in employment(profile, "past") if j.get("crustdata_company_id") == x.get("company_id")]
        return PARTIAL, (f"{name} did work at {job.get('name')} as {job.get('title')} ({span}), but is no longer at the company "
                         f"(left {', '.join(e for e in ended if e) or 'on an unrecorded date'}) {cite(r, ref)}.")
    if p.get("years") and years is not None and abs(years - p["years"]) > 1:
        return PARTIAL, f"{name} worked at {job.get('name')} as {job.get('title')} ({span}, {years} years), not {fmt_num(p['years'])} years {cite(r, ref)}."
    return VERIFIED, f"{name} worked at {job.get('name')} as {job.get('title')} ({span}) {cite(r, ref)}."


def _hiring(p, x, r, t):
    total = x.get("job_count")
    if total is None:
        return UNVERIFIABLE, "Crustdata job search returned no count."
    if p.get("open_roles"):
        diff = pct(p["open_roles"], total)
        if abs(diff) <= t["open_roles"]["verified"]:
            return VERIFIED, f"{fmt_int(total)} open roles are listed {cite(r, 'job_count')}."
        status = PARTIAL if abs(diff) <= t["open_roles"]["partial"] else CONTRADICTED
        return status, f"{fmt_int(total)} open roles are listed {cite(r, 'job_count')}; the claim is {fmt_pct(diff)} off."
    category = (p.get("category") or "").lower()
    buckets = x.get("category_buckets") or []
    count = next((b["count"] for b in buckets if (b.get("key") or "").lower() == category), 0)
    share = round(100 * count / total, 1) if total else 0
    if count >= 10 or (total and share >= 10):
        return VERIFIED, f"{fmt_int(count)} of {fmt_int(total)} open roles are {category} ({share}%) {cite(r, 'category_buckets')} {cite(r, 'job_count')}."
    if count > 0:
        return PARTIAL, f"Only {fmt_int(count)} of {fmt_int(total)} open roles are {category} {cite(r, 'category_buckets')}."
    return CONTRADICTED, f"No open {category} roles among {fmt_int(total)} listings {cite(r, 'job_count')}."


def _revenue(p, x, r, t):
    low, high = x.get("revenue_lower"), x.get("revenue_upper")
    if low is None and high is None:
        return UNVERIFIABLE, "Crustdata has no revenue data for this company; ask for financials."
    claimed = p["amount_usd"]
    rng = f"{fmt_usd(low) if low is not None else '?'} to {fmt_usd(high) if high is not None else '?'}"
    within = (low is None or claimed >= low * 0.8) and (high is None or claimed <= high * 1.2)
    refs = f"{cite(r, 'revenue_lower')} {cite(r, 'revenue_upper')}".strip()
    if within:
        return PARTIAL, f"Consistent with Crustdata's modeled revenue estimate of {rng} {refs}; an estimate, not reported revenue."
    return UNSUPPORTED, f"Outside Crustdata's modeled revenue estimate of {rng} {refs}; estimates are modeled, so ask for financials."


def _other(p, x, r, t):
    return UNVERIFIABLE, "This kind of claim cannot be checked against Crustdata's company and people data."


COMPARATORS = {
    "founded_year": _founded_year, "headcount": _headcount, "total_funding": _total_funding, "round": _round,
    "person_role": _person_role, "prior_employer": _prior_employer, "hiring": _hiring, "revenue": _revenue,
    "other": _other,
}


# ---------------------------------------------------------------- helpers (pure)

def headcount_stability(total, timeseries, swing_pct: float = 40, total_vs_series_pct: float = 15) -> tuple[bool, str]:
    points = [pt for pt in (timeseries or []) if pt.get("employee_count")]
    if len(points) < 2:
        return True, ""
    points.sort(key=lambda pt: pt["date"])
    last_date = date.fromisoformat(points[-1]["date"][:10])
    recent = [pt for pt in points if (last_date - date.fromisoformat(pt["date"][:10])).days <= 120]
    swings = []
    for a, b in zip(recent, recent[1:]):
        change = pct(b["employee_count"], a["employee_count"])
        if abs(change) > swing_pct:
            swings.append(f"{fmt_int(a['employee_count'])} on {a['date'][:10]} to {fmt_int(b['employee_count'])} on {b['date'][:10]}")
    latest = points[-1]["employee_count"]
    reasons = []
    if swings:
        reasons.append(f"week-on-week swings over {fmt_num(swing_pct)}% ({'; '.join(swings[:3])})")
    if total and abs(pct(total, latest)) > total_vs_series_pct:
        reasons.append(f"reported total {fmt_int(total)} disagrees with the latest series point {fmt_int(latest)} ({points[-1]['date'][:10]})")
    return (not reasons), "; ".join(reasons) + ("." if reasons else "")


def employment(profile: dict, which: str) -> list:
    return (profile.get("experience", {}).get("employment_details", {}).get(which)) or []


def same_org(a: str, b: str) -> bool:
    na, nb = _org_tokens(a), _org_tokens(b)
    if not na or not nb:
        return False
    return na <= nb or nb <= na


def _org_tokens(name: str) -> set:
    stop = {"inc", "llc", "ltd", "corp", "corporation", "co", "the", "group", "capital", "ventures", "partners", "vc", "fund"}
    tokens = set(re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()).split()) - stop
    return tokens


def tenure_years(start: str | None, end: str | None):
    if not start:
        return None
    s = date.fromisoformat(start[:10])
    e = date.fromisoformat(end[:10]) if end else date(2026, 10, 31)
    return round((e - s).days / 365.25, 1)


def pct(claimed, actual) -> float:
    return round(100.0 * (claimed - actual) / actual, 1) if actual else 0.0


def cite(refs: dict, name: str) -> str:
    fid = refs.get(name)
    return f"[{fid}]" if fid else ""


def label_round(rtype: str | None) -> str:
    if not rtype:
        return "unknown round"
    return rtype.replace("_", " ").title().replace("Series ", "Series ")


def fmt_usd(v) -> str:
    v = float(v)
    if v >= 1e9:
        return f"${v / 1e9:.2f}B".replace(".00B", "B")
    if v >= 1e6:
        return f"${v / 1e6:.1f}M".replace(".0M", "M")
    if v >= 1e3:
        return f"${v / 1e3:.0f}K"
    return f"${v:,.0f}"


def fmt_int(v) -> str:
    return f"{int(round(float(v))):,}"


def fmt_num(v) -> str:
    v = float(v)
    return str(int(v)) if v.is_integer() else str(v)


def fmt_pct(v) -> str:
    return f"{'+' if v > 0 else ''}{v:.0f}%"
