"""Resolve-before-act: map a company mention to one Crustdata company ID, or refuse to guess.

Live finding that motivates this: identify(names=["Mercury"]) returns 25 companies, all at
confidence 1.0, and "Mercury Technologies" ranks the real fintech at 0.6 behind unrelated firms.
"""

import re
from dataclasses import dataclass, field

from . import trace
from .ledger import Ledger
from .proxy import CrustdataClient, ToolError

MARGIN = 0.5
SECTOR_INDUSTRIES = {
    "fintech": ["financial services", "banking", "fintech"],
    "banking": ["financial services", "banking"],
    "payments": ["financial services", "payments"],
    "insurance": ["insurance"],
    "healthcare": ["hospitals", "health", "medical"],
    "logistics": ["logistics", "transportation", "supply chain"],
    "software": ["software", "technology, information and internet", "it services"],
    "saas": ["software", "technology, information and internet"],
    "ai": ["software", "technology, information and internet", "research"],
    "ecommerce": ["retail", "internet", "e-commerce"],
}
STOPWORDS = {"inc", "inc.", "ltd", "llc", "corp", "corporation", "technologies", "technology", "labs", "the", "co", "company"}


@dataclass
class Resolution:
    status: str  # RESOLVED | AMBIGUOUS | NOT_FOUND
    company_id: int | None = None
    name: str | None = None
    domain: str | None = None
    candidates: list = field(default_factory=list)
    rationale: str = ""
    decision_seq: int | None = None


def resolve_company(client: CrustdataClient, ledger: Ledger, mention: str | None, domain: str | None,
                    founders: list[str], sector: str | None, claimed_founded: int | None,
                    claimed_headcount: int | None) -> Resolution:
    trace.step(f"Resolving company: mention={mention!r} domain={domain!r}")

    if domain:
        try:
            r = client.post("/company/identify", {"domains": [domain]}, f"identify domain {domain}")
            matches = _matches(r.data)
            if matches:
                info = matches[0]["company_data"]["basic_info"]
                return _decide(ledger, mention or domain, "RESOLVED", info, [], f"exact domain match on {domain}", [r.seq])
        except ToolError as exc:
            trace.warn(f"domain identify failed: {exc}")

    if not mention:
        return _decide(ledger, domain or "", "NOT_FOUND", None, [], "no company name or resolvable domain in request", [])

    r = client.post("/company/identify", {"names": [mention]}, f"identify name {mention!r}")
    receipts = [r.seq]
    candidates = []
    for m in _matches(r.data):
        info = m["company_data"]["basic_info"]
        score, reasons = _score(info, m.get("confidence_score") or 0, mention, sector, claimed_founded, claimed_headcount)
        candidates.append({"crustdata_company_id": info["crustdata_company_id"], "name": info.get("name"),
                           "domain": info.get("primary_domain"), "confidence": m.get("confidence_score"),
                           "score": score, "reasons": reasons, "_info": info})
    trace.info(f"identify returned {len(candidates)} candidates; "
               f"{sum(1 for c in candidates if c['confidence'] == 1.0)} at confidence 1.0")

    if founders:
        anchored = _founder_cross_check(client, founders, mention)
        if anchored:
            receipts.append(anchored["seq"])
            for c in candidates:
                if c["crustdata_company_id"] in anchored["company_ids"]:
                    c["score"] += 2.0
                    c["reasons"].append(f"founder {anchored['person']} currently works here (person search)")
            known = {c["crustdata_company_id"] for c in candidates}
            for cid, cinfo in anchored["companies"].items():
                if cid not in known:
                    candidates.append({"crustdata_company_id": cid, "name": cinfo["name"], "domain": cinfo["domain"],
                                       "confidence": None, "score": 2.0,
                                       "reasons": [f"founder {anchored['person']} currently works here (person search)"],
                                       "_info": {"crustdata_company_id": cid, "name": cinfo["name"], "primary_domain": cinfo["domain"]}})

    candidates.sort(key=lambda c: c["score"], reverse=True)
    if not candidates:
        return _decide(ledger, mention, "NOT_FOUND", None, [], "identify returned no candidates", receipts)

    # Only a candidate whose name actually matches (same significant tokens), or that a founder
    # currently works at, may be chosen. Fuzzy near-names are listed, never picked.
    eligible = [c for c in candidates if _same_name(c["name"], mention) or any("founder" in r for r in c["reasons"])]
    if not eligible:
        return _decide(ledger, mention, "NOT_FOUND", None, candidates,
                       f"no company named {mention!r} found; closest names are only partial matches", receipts)
    candidates = eligible + [c for c in candidates if c not in eligible]
    top = candidates[0]
    second = eligible[1]["score"] if len(eligible) > 1 else -1
    if top["score"] - second >= MARGIN:
        return _decide(ledger, mention, "RESOLVED", top["_info"], candidates,
                       f"top candidate leads by {top['score'] - second:.2f} (margin {MARGIN}): " + "; ".join(top["reasons"]),
                       receipts)
    return _decide(ledger, mention, "AMBIGUOUS", None, candidates,
                   f"top two candidates within {MARGIN} ({top['name']} {top['score']:.2f} vs {candidates[1]['name']} {second:.2f}); "
                   "add a domain or founder name", receipts)


def _founder_cross_check(client: CrustdataClient, founders: list[str], mention: str):
    token = _primary_token(mention)
    for founder in founders:
        conditions = [
            {"field": "basic_profile.name", "type": "(.)", "value": founder},
            {"field": "experience.employment_details.current.seniority_level", "type": "in",
             "value": ["CXO", "Owner / Partner", "Vice President"]},
        ]
        if token:
            conditions.append({"field": "experience.employment_details.current.company_name", "type": "(.)", "value": token})
        try:
            r = client.post("/person/search", {"filters": {"op": "and", "conditions": conditions}, "limit": 10,
                                               "fields": ["basic_profile.name", "experience.employment_details.current"]},
                            f"founder cross-check {founder!r}")
        except ToolError as exc:
            trace.warn(f"founder cross-check failed: {exc}")
            continue
        companies = {}
        for p in r.data.get("profiles", []):
            for job in (p.get("experience", {}).get("employment_details", {}).get("current") or []):
                cid = job.get("crustdata_company_id")
                if cid and (not token or token in (job.get("name") or "").lower()):
                    domain = re.sub(r"^https?://(www\.)?", "", job.get("company_website") or "").strip("/") or None
                    companies[cid] = {"name": job.get("name"), "domain": domain}
        if companies:
            return {"seq": r.seq, "person": founder, "company_ids": set(companies), "companies": companies}
    return None


def _score(info: dict, confidence: float, mention: str, sector: str | None, founded: int | None, headcount: int | None):
    score, reasons = confidence, [f"identify confidence {confidence}"]
    if _norm(info.get("name")) == _norm(mention):
        score += 0.5
        reasons.append("exact name match")
    elif _same_name(info.get("name"), mention):
        score += 0.3
        reasons.append("same name ignoring suffixes")
    if sector:
        industries = " ".join(info.get("industries") or []).lower() + " " + (info.get("description") or "").lower()
        if any(word in industries for word in SECTOR_INDUSTRIES.get(sector, [sector])):
            score += 0.3
            reasons.append(f"industry matches '{sector}'")
    if founded and info.get("year_founded"):
        if info["year_founded"] == founded:
            score += 0.3
            reasons.append("founded year matches")
        elif abs(info["year_founded"] - founded) == 1:
            score += 0.15
            reasons.append("founded year within 1")
    if headcount and info.get("employee_count_range") and _range_fits(info["employee_count_range"], headcount):
        score += 0.2
        reasons.append("size range compatible")
    return round(score, 3), reasons


def _decide(ledger, mention, status, info, candidates, rationale, receipts) -> Resolution:
    public = [{k: v for k, v in c.items() if k != "_info"} for c in candidates[:6]]
    entry = ledger.append("decision", {
        "question": f"Which company does {mention!r} refer to?",
        "status": status,
        "chosen": info.get("crustdata_company_id") if info else None,
        "candidates": public,
        "rationale": rationale,
        "evidence_receipts": receipts,
    })
    if status == "RESOLVED":
        trace.ok(f"RESOLVED → {info.get('name')} ({info.get('primary_domain')}) id {info['crustdata_company_id']} · {rationale}")
    else:
        trace.warn(f"{status}: {rationale}")
        for c in public[:4]:
            trace.info(f"   candidate {c['name']} ({c['domain']}) id {c['crustdata_company_id']} score {c['score']}")
    return Resolution(status=status, company_id=info.get("crustdata_company_id") if info else None,
                      name=info.get("name") if info else None, domain=info.get("primary_domain") if info else None,
                      candidates=public, rationale=rationale, decision_seq=entry["seq"])


def _same_name(a: str | None, b: str | None) -> bool:
    ta = {t for t in _norm(a).split() if t not in STOPWORDS}
    tb = {t for t in _norm(b).split() if t not in STOPWORDS}
    return bool(ta) and ta == tb


def _matches(data) -> list:
    if isinstance(data, list) and data:
        return data[0].get("matches") or []
    return []


def _norm(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _primary_token(mention: str) -> str | None:
    tokens = [t for t in _norm(mention).split() if t not in STOPWORDS]
    return tokens[0] if tokens else None


def _range_fits(rng: str, headcount: int) -> bool:
    nums = [int(n) for n in re.findall(r"\d+", rng.replace(",", ""))]
    if not nums:
        return False
    low = nums[0]
    high = nums[1] if len(nums) > 1 else 10 ** 9
    return low * 0.5 <= headcount <= high * 2
