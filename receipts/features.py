"""Company features for preference learning: pure functions of receipt-backed fact values.

Every input is a fact (JSON pointer into a stored API response), and every transform is fixed,
so verify can recompute each feature vector from the raw bytes.
"""

import math
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
