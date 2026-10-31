"""Company features for preference learning: pure functions of receipt-backed fact values.

Every input is a fact (JSON pointer into a stored API response), and every transform is fixed,
so verify can recompute each feature vector from the raw bytes.
"""

import math
import re
from datetime import date

from .claims import headcount_stability

FEATURES = ["growth_yoy", "eng_hiring_share", "open_roles", "months_since_round", "headcount", "total_funding", "stage", "company_age"]
LABELS = {
    "growth_yoy": "year-on-year headcount growth",
    "eng_hiring_share": "share of open roles in engineering",
    "open_roles": "number of open roles",
    "months_since_round": "months since the last funding round",
    "headcount": "team size",
    "total_funding": "total funding raised",
    "stage": "funding stage",
    "company_age": "company age",
}
# how to describe a feature value that is above / below the fund's typical company
DIRECTION = {
    "growth_yoy": ("fast headcount growth", "slow or negative headcount growth"),
    "eng_hiring_share": ("engineering-heavy hiring", "little engineering hiring"),
    "open_roles": ("many open roles", "few open roles"),
    "months_since_round": ("last round a while ago", "recent funding round"),
    "headcount": ("large team", "small team"),
    "total_funding": ("well funded", "lightly funded"),
    "stage": ("later stage", "earlier stage"),
    "company_age": ("older company", "young company"),
}


def reason(feature: str, value: float, contribution: float) -> str:
    high, low = DIRECTION[feature]
    return f"{'+' if contribution >= 0 else '−'} {high if value > 0 else low}"


STAGES = {"pre_seed": 0, "angel": 0, "seed": 1, "series_a": 2, "series_b": 3, "series_c": 4, "series_d": 5,
          "series_e": 6, "series_f": 6, "private_equity": 5, "debt_financing": 2, "venture_round": 2}
# fixed standardisation: (transform(x) - center) / scale, clipped to [-3, 3]
SCALE = {
    "growth_yoy": (0.3, 0.4), "eng_hiring_share": (0.2, 0.15), "open_roles": (1.0, 0.6), "months_since_round": (18, 12),
    "headcount": (2.3, 0.6), "total_funding": (7.0, 0.8), "stage": (2, 1), "company_age": (6, 4),
}


def company_count(buckets, company_id) -> int:
    for b in buckets or []:
        if str(b.get("key")) == str(company_id):
            return int(b.get("count") or 0)
    return 0


def compute(v: dict, as_of: str) -> dict:
    """v: raw fact values for one company. Returns {"raw": display values, "vector": standardised, "missing": [...]}."""
    asof = date.fromisoformat(as_of[:10])
    raw, missing = {}, []

    headcount = v.get("headcount_total")
    stable, why = headcount_stability(headcount, v.get("timeseries"))
    raw["headcount"] = headcount
    growth = v.get("growth_yoy")
    raw["growth_yoy"] = None if growth is None or not stable else round(float(growth), 1)
    if growth is not None and not stable:
        raw["growth_excluded"] = f"headcount series unstable: {why}"

    open_roles = company_count(v.get("job_buckets"), v.get("company_id"))
    eng_roles = company_count(v.get("eng_buckets"), v.get("company_id"))
    raw["open_roles"] = open_roles
    raw["eng_roles"] = eng_roles
    raw["eng_hiring_share"] = round(eng_roles / open_roles, 3) if open_roles else None

    raw["total_funding"] = v.get("total_funding")
    raw["last_round_type"] = v.get("last_round_type")
    raw["stage"] = STAGES.get((v.get("last_round_type") or "").lower())
    last = v.get("last_fundraise_date")
    raw["last_fundraise_date"] = last[:10] if last else None
    raw["months_since_round"] = (round((asof - date.fromisoformat(last[:10])).days / 30.44, 1) if last else None)
    founded = v.get("year_founded")
    raw["company_age"] = asof.year - founded if founded else None

    transformed = {
        "growth_yoy": None if raw["growth_yoy"] is None else max(-1.0, min(3.0, raw["growth_yoy"] / 100)),
        "eng_hiring_share": raw["eng_hiring_share"],
        "open_roles": math.log10(open_roles + 1),
        "months_since_round": raw["months_since_round"],
        "headcount": math.log10(headcount) if headcount else None,
        "total_funding": math.log10(raw["total_funding"]) if raw["total_funding"] else None,
        "stage": raw["stage"],
        "company_age": raw["company_age"],
    }
    vector = {}
    for name in FEATURES:
        value = transformed[name]
        if value is None:
            missing.append(name)
            vector[name] = 0.0
        else:
            center, scale = SCALE[name]
            vector[name] = round(max(-3.0, min(3.0, (value - center) / scale)), 6)
    # Optional people-graph and identity signals: only when the run requested them (keeps older runs reproducible).
    if "founders" in v:
        raw["founders"] = founder_signals(v.get("founders"), v.get("company_id"))
    if "regions" in v:
        raw["identity_collision"] = identity_collision(v.get("regions"), headcount)
    return {"raw": raw, "vector": vector, "missing": missing, "stable_headcount": stable}


def thesis_violations(raw: dict, country: str | None, strategy: dict) -> list[str]:
    thesis = strategy.get("thesis", {})
    problems = []
    lo, hi = thesis.get("headcount", [0, 10 ** 9])
    if raw.get("headcount") is not None and not lo <= raw["headcount"] <= hi:
        problems.append(f"thesis.headcount {lo}-{hi} (has {raw['headcount']})")
    rounds = thesis.get("last_round")
    if rounds and raw.get("last_round_type") and raw["last_round_type"] not in rounds:
        problems.append(f"thesis.last_round {rounds} (has {raw['last_round_type']})")
    return problems


# ---------------------------------------------------------------- people graph & identity checks
# Display-and-guardrail signals (not model features), so adding them does not change the learned model.

FOUNDER_TITLE = re.compile(r"\b(co-?\s?founder|founder)\b", re.I)
NOT_FOUNDER = re.compile(r"\b(assistant|associate|advisor|adviser|office of|chief of staff)\b.*\bfounder|\bto (the )?(co-?)?founder", re.I)
TECH_TITLE = re.compile(r"\b(cto|engineer|engineering|developer|architect|scientist|technical|software|sde|programmer)\b", re.I)
BIG_TECH = {"google", "microsoft", "amazon", "meta", "facebook", "apple", "netflix", "stripe", "uber", "airbnb", "linkedin",
            "salesforce", "oracle", "adobe", "nvidia", "intel", "ibm", "cisco", "twitter", "paypal", "flipkart", "razorpay",
            "swiggy", "zomato", "paytm", "phonepe", "freshworks", "zoho", "cred", "ola", "meesho", "zerodha", "atlassian",
            "goldman sachs", "mckinsey", "bain", "boston consulting group", "jpmorgan", "morgan stanley"}


def founder_signals(founders: list | None, company_id) -> dict | None:
    """Verify listed founders (a current role at THIS company with a founder title) and summarise their backgrounds."""
    if founders is None:
        return None
    cid = str(company_id)
    verified = []
    for p in founders:
        name = (p.get("basic_profile") or {}).get("name")
        jobs = (p.get("experience") or {}).get("employment_details") or {}
        here = [j for j in jobs.get("current") or [] if cid in [str(x) for x in (j.get("employer_company_id") or [])]]
        titles_here = [j.get("employee_title") or "" for j in here]
        if not name or not any(FOUNDER_TITLE.search(t) and not NOT_FOUNDER.search(t) for t in titles_here):
            continue
        past = [j for j in jobs.get("past") or [] if cid not in [str(x) for x in (j.get("employer_company_id") or [])]]
        all_titles = titles_here + [j.get("employee_title") or "" for j in past]
        big = sorted({(j.get("employer_name") or "").strip() for j in past
                      if (j.get("employer_name") or "").strip().lower() in BIG_TECH})
        verified.append({
            "name": name,
            "title": "; ".join(t for t in titles_here if t),
            "technical": any(TECH_TITLE.search(t) for t in all_titles),
            "repeat_founder": any(FOUNDER_TITLE.search(j.get("employee_title") or "") for j in past),
            "big_tech": big,
        })
    return {
        "listed": len(founders),
        "verified": verified,
        "technical": any(f["technical"] for f in verified),
        "repeat_founder": any(f["repeat_founder"] for f in verified),
        "big_tech": sorted({b for f in verified for b in f["big_tech"]}),
    }


def identity_collision(regions: dict | None, total) -> str | None:
    """A single region larger than the whole company suggests the record is merged with another entity.
    Uses the largest single region, never a sum (regions overlap: 'United States' contains 'California')."""
    if not regions or not total:
        return None
    region, count = max(regions.items(), key=lambda kv: kv[1] or 0)
    if (count or 0) > 1.3 * total:
        return f"region '{region}' reports {count:,} employees but the company total is {total:,} (record may be merged with another entity)"
    return None
