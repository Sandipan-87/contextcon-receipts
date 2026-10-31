"""Turn a free-text pitch into typed, checkable claims.

Claude (structured JSON output) is used when ANTHROPIC_API_KEY is set; otherwise, or on any
LLM failure, a deterministic rule-based extractor runs. Either way the output has one schema,
and the extractor that produced it is recorded in the ledger.
"""

import json
import re

from . import trace
from .config import anthropic_api_key, anthropic_model

CLAIM_TYPES = ["founded_year", "headcount", "total_funding", "round", "person_role", "prior_employer", "hiring", "revenue", "other"]
SECTORS = ["fintech", "banking", "payments", "insurance", "healthcare", "logistics", "saas", "software", "ai", "ecommerce"]

_NULLABLE_STR = {"type": ["string", "null"]}
_NULLABLE_NUM = {"type": ["number", "null"]}
PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        "year": _NULLABLE_NUM, "value": _NULLABLE_NUM, "amount_usd": _NULLABLE_NUM,
        "round_type": _NULLABLE_STR, "lead_investor": _NULLABLE_STR, "person": _NULLABLE_STR,
        "role": _NULLABLE_STR, "company": _NULLABLE_STR, "years": _NULLABLE_NUM,
        "category": _NULLABLE_STR, "open_roles": _NULLABLE_NUM, "metric": _NULLABLE_STR,
    },
    "required": ["year", "value", "amount_usd", "round_type", "lead_investor", "person", "role",
                 "company", "years", "category", "open_roles", "metric"],
    "additionalProperties": False,
}
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "company_name": _NULLABLE_STR,
        "domain": _NULLABLE_STR,
        "sector": _NULLABLE_STR,
        "founders": {"type": "array", "items": {"type": "string"}},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": CLAIM_TYPES},
                    "text": {"type": "string"},
                    "params": PARAMS_SCHEMA,
                },
                "required": ["type", "text", "params"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["company_name", "domain", "sector", "founders", "claims"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You extract factual, checkable claims from a startup founder's pitch for a diligence analyst.
Return only what the text states; never infer or add facts. Use these claim types:
- founded_year: params.year
- headcount: params.value (number of employees)
- total_funding: params.amount_usd (total raised to date)
- round: params.round_type (e.g. "series_d", "seed"), params.amount_usd, params.lead_investor
- person_role: params.person (name as written), params.role (e.g. "CTO")
- prior_employer: params.person, params.role, params.company, params.years (tenure if stated)
- hiring: params.category (e.g. "engineering"), params.open_roles if a number is stated
- revenue: params.amount_usd, params.metric (e.g. "ARR")
- other: any other factual claim (params all null)
Expand amounts to full USD numbers (e.g. "$200M" -> 200000000). Set unused params to null.
company_name is the startup's name as written; domain only if a website appears in the text;
sector is one lowercase word if obvious (fintech, payments, insurance, healthcare, logistics, saas, ai, ecommerce), else null;
founders lists the full names of founders/executives that appear in the text. Each claim's text is the exact source sentence."""


def extract(pitch: str) -> tuple[dict, str]:
    """Returns (extraction, extractor_name)."""
    if anthropic_api_key():
        try:
            return _number_claims(_extract_llm(pitch)), f"llm:{anthropic_model()}"
        except Exception as exc:  # any LLM problem falls back to deterministic rules
            trace.warn(f"LLM extraction failed ({exc.__class__.__name__}: {str(exc)[:120]}); using rule-based extractor")
    return _number_claims(extract_rules(pitch)), "rules"


def _extract_llm(pitch: str) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=anthropic_model(),
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"<pitch>\n{pitch}\n</pitch>"}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model refused the extraction request")
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    for claim in data.get("claims", []):
        if claim["type"] == "round" and claim["params"].get("round_type"):
            claim["params"]["round_type"] = normalize_round(claim["params"]["round_type"])
    return data


# ---------------------------------------------------------------- rule-based fallback

_AMOUNT = r"\$\s?(\d+(?:\.\d+)?)\s*(k|K|m|M|mm|mn|million|Million|b|B|bn|billion|Billion)?"
_NAME = r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"
_ORG = r"[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3}"
_ROLES = r"CEO|CTO|COO|CFO|CPO|CMO|[Cc]o-?[Ff]ounder|[Ff]ounder"


def extract_rules(pitch: str) -> dict:
    text = " ".join(pitch.split())
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    out = {"company_name": None, "domain": None, "sector": None, "founders": [], "claims": []}

    m = re.search(rf"\b(?:{_ROLES})\s+(?:and\s+\w+\s+)?(?:of|at)\s+({_ORG})", text)
    if m:
        out["company_name"] = re.sub(r"\s+(?:We|Our|and)$", "", m.group(1)).strip(" .,")
    m = re.search(r"\b((?:[a-z0-9\-]+\.)+(?:com|io|ai|co|in|app|dev|xyz|org|net))\b", text)
    if m:
        out["domain"] = m.group(1)
    lowered = text.lower()
    out["sector"] = next((s for s in SECTORS if re.search(rf"\b{s}\b", lowered)), None)

    for m in re.finditer(rf"\b(?:I'm|I am|my name is|This is)\s+({_NAME})", text):
        out["founders"].append(m.group(1))

    for s in sentences:
        claims = out["claims"]
        if m := re.search(r"\b(?:founded|started|incorporated|launched)\s+(?:in\s+)?((?:19|20)\d{2})", s, re.I):
            claims.append(_claim("founded_year", s, year=int(m.group(1))))
        if m := re.search(r"(\d[\d,]*(?:\.\d+)?\s*[kK]?)\+?\s*(?:people|employees|staff|team members|FTEs|person team)", s) \
                or re.search(r"team of (\d[\d,]*(?:\.\d+)?\s*[kK]?)", s):
            claims.append(_claim("headcount", s, value=parse_count(m.group(1))))
        round_m = re.search(rf"{_AMOUNT}\s+(pre-seed|seed|series\s+[a-hA-H])\b", s, re.I) \
            or re.search(rf"(pre-seed|seed|series\s+[a-hA-H])\b[^.$]*?{_AMOUNT}", s, re.I)
        if round_m:
            groups = round_m.groups()
            if groups[0] and groups[0][0].isdigit():
                amount, rtype = parse_amount(groups[0], groups[1]), groups[2]
            else:
                rtype, amount = groups[0], parse_amount(groups[1], groups[2])
            lead = re.search(rf"led by\s+({_ORG})", s)
            claims.append(_claim("round", s, round_type=normalize_round(rtype), amount_usd=amount,
                                 lead_investor=lead.group(1).strip(" .,") if lead else None))
        elif m := re.search(rf"raised\s+(?:a total of\s+|over\s+|more than\s+)?{_AMOUNT}", s, re.I):
            claims.append(_claim("total_funding", s, amount_usd=parse_amount(m.group(1), m.group(2))))
        if m := re.search(rf"{_AMOUNT}\s*(?:in\s+)?(ARR|annual recurring revenue|revenue|annual revenue|MRR)", s, re.I):
            claims.append(_claim("revenue", s, amount_usd=parse_amount(m.group(1), m.group(2)), metric=m.group(3).upper()))
        for m in re.finditer(rf"\b({_ROLES})\s*,?\s+({_NAME})\b", s):
            role, person = m.group(1), m.group(2)
            if person.split()[0] in {"Of", "At", "And", "The"}:
                continue
            prior = re.search(rf"(?:previously at|formerly at|was at|worked at|came from|ex-|spent\s+(\d+)\s+years?\s+at|previously worked at|before that at|joined us from)\s*({_ORG})", s[m.end():])
            if prior:
                claims.append(_claim("prior_employer", s, person=person, role=role.upper() if len(role) <= 3 else role,
                                     company=prior.group(2).strip(" .,"), years=int(prior.group(1)) if prior.group(1) else None))
            else:
                claims.append(_claim("person_role", s, person=person, role=role.upper() if len(role) <= 3 else role))
            if person not in out["founders"]:
                out["founders"].append(person)
        for m in re.finditer(rf"\b(?:I'm|I am)\s+({_NAME})\s*,?\s+(?:the\s+)?({_ROLES})\b", s):
            claims.append(_claim("person_role", s, person=m.group(1), role=m.group(2).upper() if len(m.group(2)) <= 3 else m.group(2)))
        if m := re.search(r"hiring\s+(?:heavily|aggressively|rapidly|fast|actively)?\s*(?:in|for|across)\s+(engineering|sales|product|marketing|operations|design)", s, re.I):
            claims.append(_claim("hiring", s, category=m.group(1).lower()))
        elif m := re.search(r"(\d[\d,]*)\s+open\s+(?:roles|positions|jobs)", s, re.I):
            claims.append(_claim("hiring", s, open_roles=parse_count(m.group(1))))
    return out


def _claim(ctype: str, text: str, **params) -> dict:
    full = {k: None for k in PARAMS_SCHEMA["properties"]}
    full.update(params)
    return {"type": ctype, "text": text, "params": full}


def _number_claims(data: dict) -> dict:
    seen, claims = set(), []
    for c in data.get("claims", []):
        key = (c["type"], json.dumps(c["params"], sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        claims.append({"claim_id": f"C{len(claims) + 1}", **c})
    data["claims"] = claims
    return data


def parse_amount(number: str, unit: str | None) -> float:
    value = float(number)
    unit = (unit or "").lower()
    if unit in {"k"}:
        value *= 1e3
    elif unit in {"m", "mm", "mn", "million"}:
        value *= 1e6
    elif unit in {"b", "bn", "billion"}:
        value *= 1e9
    return value


def parse_count(raw: str) -> int:
    raw = raw.replace(",", "").strip()
    if raw.lower().endswith("k"):
        return int(float(raw[:-1]) * 1000)
    return int(float(raw))


def normalize_round(raw: str) -> str:
    return re.sub(r"[\s\-]+", "_", raw.strip().lower())
