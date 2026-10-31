"""Turn a free-text thesis ("Series A devtools in India, technical founders") into Crustdata search filters.

The LLM only proposes; code validates every value:
- industries must exist in Crustdata (checked with the free /company/search/autocomplete, each lookup a receipt)
- round types must be in the allowed set; countries are normalised; numbers are range-checked
Anything that cannot be mapped is reported back to the user, never silently dropped or invented.
The rulebook's guardrails, tolerances and autonomy limits still apply unchanged.
"""

import copy
import re

from . import llm, trace
from .proxy import CrustdataClient, ToolError

ROUND_TYPES = ["pre_seed", "seed", "series_a", "series_b", "series_c", "series_d", "series_e", "series_f"]
COUNTRY_ALIASES = {"usa": "United States", "us": "United States", "u.s.": "United States", "america": "United States",
                   "united states of america": "United States", "uk": "United Kingdom", "britain": "United Kingdom",
                   "england": "United Kingdom", "uae": "United Arab Emirates", "in": "India", "bharat": "India"}

SCHEMA = {
    "type": "object",
    "properties": {
        "industries": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "countries": {"type": "array", "items": {"type": "string"}},
        "rounds": {"type": "array", "items": {"type": "string"}},
        "headcount_min": {"type": ["integer", "null"]},
        "headcount_max": {"type": ["integer", "null"]},
        "raised_since": {"type": ["string", "null"]},
        "not_searchable": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["industries", "keywords", "countries", "rounds", "headcount_min", "headcount_max", "raised_since", "not_searchable"],
    "additionalProperties": False,
}
SYSTEM = f"""You translate a venture investor's thesis into company-search filters.
- industries: LinkedIn-style industry names (e.g. "Software Development", "Financial Services",
  "Technology, Information and Internet", "Hospitals and Health Care", "Truck Transportation"); 1-3 values.
- keywords: 1-3 short words or phrases that should appear in a company's description (e.g. "developer", "API", "payments").
- countries: full English country names.
- rounds: any of {ROUND_TYPES}.
- headcount_min / headcount_max: integers if the thesis implies a team size, else null.
- raised_since: ISO date if the thesis implies recency (e.g. "raised in the last year"), else null.
- not_searchable: thesis criteria that cannot be expressed with these filters (e.g. "technical founders", "strong moat").
Use only what the thesis says; leave fields empty or null rather than guessing."""


def interpret(text: str, client: CrustdataClient, base_thesis: dict) -> dict:
    """Returns {"thesis": merged filters, "mapping": what was proposed/validated/unmapped, "model": llm used}."""
    trace.step("Interpreting your thesis")
    trace.info(f"“{text.strip()}”")
    proposal, model = None, "rules"
    if llm.available():
        try:
            proposal, model = llm.chat_json(SYSTEM, f"Thesis: {text}", SCHEMA)
        except Exception as exc:
            trace.warn(f"LLM could not interpret the thesis ({exc.__class__.__name__}); using keyword rules")
    if not isinstance(proposal, dict):
        proposal = _rules(text)

    mapping = {"proposed": proposal, "model": model, "industries": [], "unmapped": [], "notes": []}
    industries = []
    for name in (proposal.get("industries") or [])[:4]:
        hit = _validate_industry(client, str(name))
        if hit:
            industries.append(hit)
            mapping["industries"].append({"proposed": name, "matched": hit})
        else:
            mapping["unmapped"].append(f"industry “{name}” (not a Crustdata industry)")

    countries = []
    for c in proposal.get("countries") or []:
        norm = COUNTRY_ALIASES.get(str(c).strip().lower(), str(c).strip().title() if str(c).islower() else str(c).strip())
        if norm and norm not in countries:
            countries.append(norm)
    rounds = []
    for r in proposal.get("rounds") or []:
        norm = re.sub(r"[\s\-]+", "_", str(r).strip().lower())
        if norm in ROUND_TYPES:
            rounds.append(norm)
        else:
            mapping["unmapped"].append(f"round “{r}”")
    keywords = [k.strip() for k in (proposal.get("keywords") or []) if isinstance(k, str) and 2 <= len(k.strip()) <= 40][:3]
    lo, hi = proposal.get("headcount_min"), proposal.get("headcount_max")
    since = proposal.get("raised_since")
    if since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(since)):
        mapping["unmapped"].append(f"date “{since}”")
        since = None
    mapping["unmapped"] += [f"“{n}” (not searchable on company data; judge it yourself)" for n in proposal.get("not_searchable") or []]

    thesis = copy.deepcopy(base_thesis)
    if industries:
        thesis["sectors"] = industries
    else:
        mapping["notes"].append("no industry could be mapped; kept the rulebook's sectors")
    if countries:
        thesis["hq_countries"] = countries
    if rounds:
        thesis["last_round"] = rounds
    if isinstance(lo, int) or isinstance(hi, int):
        thesis["headcount"] = [lo if isinstance(lo, int) and lo >= 1 else thesis["headcount"][0],
                               hi if isinstance(hi, int) and hi >= 1 else thesis["headcount"][1]]
    if since:
        thesis["raised_since"] = since
    if keywords:
        thesis["description_keywords"] = keywords
    trace.ok("filters: " + "; ".join(f"{k}={v}" for k, v in thesis.items()))
    for u in mapping["unmapped"]:
        trace.warn(f"not used as a filter: {u}")
    return {"thesis": thesis, "mapping": mapping, "model": model, "text": text}


def _validate_industry(client: CrustdataClient, name: str) -> str | None:
    queries = [name] + [w for w in re.findall(r"[A-Za-z]{4,}", name)[:2]]
    for q in queries:
        try:
            r = client.post("/company/search/autocomplete",
                            {"field": "taxonomy.professional_network_industry", "query": q, "limit": 10}, f"validate industry {q!r}")
        except ToolError:
            continue
        values = [s.get("value") for s in r.data.get("suggestions", []) if s.get("value")]
        exact = next((v for v in values if v.lower() == name.lower()), None)
        if exact:
            return exact
        if q != name and values:
            return values[0]
    return None


def _rules(text: str) -> dict:
    t = text.lower()
    rounds = [r for r in ROUND_TYPES if r.replace("_", " ") in t or r.replace("_", "-") in t]
    countries = [c for c in ["India", "United States", "United Kingdom", "Singapore", "Germany"] if c.lower() in t]
    countries += [COUNTRY_ALIASES[a] for a in ("usa", "us", "uk") if re.search(rf"\b{a}\b", t) and COUNTRY_ALIASES[a] not in countries]
    industries = [i for k, i in {"fintech": "Financial Services", "payments": "Financial Services", "software": "Software Development",
                                 "saas": "Software Development", "devtools": "Software Development", "health": "Hospitals and Health Care",
                                 "logistics": "Transportation, Logistics, Supply Chain and Storage"}.items() if k in t]
    return {"industries": list(dict.fromkeys(industries)), "keywords": [], "countries": countries, "rounds": rounds,
            "headcount_min": None, "headcount_max": None, "raised_since": None, "not_searchable": []}
