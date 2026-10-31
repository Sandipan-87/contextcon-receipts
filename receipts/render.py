"""Deterministic memo renderer.

The report is a pure function of meta.json, claims.json and facts.json, so `verify` can
re-render it and require byte equality: no sentence, number or name can appear in the memo
unless it came from a claim or a fact with a receipt.
"""

import json
import re

from .claims import CONTRADICTED, PARTIAL, STATUS_ORDER, UNSUPPORTED, UNVERIFIABLE, VERIFIED

ICONS = {VERIFIED: "✅", PARTIAL: "🟡", CONTRADICTED: "❌", UNSUPPORTED: "⚠️", UNVERIFIABLE: "❔"}


def render_report(meta: dict, claims: list[dict], facts: dict[str, dict]) -> str:
    lines = []
    res = meta["resolution"]
    title = res.get("name") or meta.get("company_mention") or "Unknown company"
    lines.append(f"# Diligence memo: {title}")
    lines.append("")
    if res["status"] == "RESOLVED":
        lines.append(f"**Company:** {res['name']} ({res.get('domain') or 'no domain'}), Crustdata company ID {res['company_id']}  ")
    else:
        lines.append(f"**Company:** could not be resolved ({res['status']}) for {meta.get('company_mention')!r}  ")
    lines.append(f"**Resolution:** {res['status']}: {res['rationale']} (ledger entry #{res['decision_seq']})  ")
    lines.append(f"**Run:** `{meta['run_id']}` · claims extracted by `{meta['extractor']}` · {len(claims)} claims checked  ")
    lines.append("")

    counts = {s: sum(1 for c in claims if c["status"] == s) for s in STATUS_ORDER}
    summary = ", ".join(f"{counts[s]} {s.lower()}" for s in STATUS_ORDER if counts[s])
    lines.append("## Verdict")
    lines.append("")
    if counts[CONTRADICTED] or counts[UNSUPPORTED]:
        lines.append(f"**Flag for founder call.** {summary}.")
    elif counts[VERIFIED] == len(claims) and claims:
        lines.append(f"**All checkable claims verified.** {summary}.")
    else:
        lines.append(f"**No contradictions found; some claims need documents.** {summary}.")
    lines.append("")
    if meta.get("decision"):
        d = meta["decision"]
        lines.append(f"**Agent decision: {d['decision']}** (rule from strategy/STRATEGY.md: {d['rule']}). "
                     "The resulting deal-board update and drafted email are recorded as `action` entries in the ledger.")
        lines.append("")

    if res["status"] != "RESOLVED" and res.get("candidates"):
        lines.append("## Candidate companies (not guessed)")
        lines.append("")
        for c in res["candidates"]:
            lines.append(f"- {c['name']} ({c.get('domain') or 'no domain'}), ID {c['crustdata_company_id']}, score {c['score']}")
        lines.append("")

    flags = [c for c in claims if c["status"] in (CONTRADICTED, UNSUPPORTED)]
    if flags:
        lines.append("## Red flags")
        lines.append("")
        for c in flags:
            lines.append(f"- {ICONS[c['status']]} **{c['claim_id']}** “{c['text']}” → {link_facts(c['explanation'])}")
        lines.append("")

    lines.append("## Claim-by-claim")
    lines.append("")
    lines.append("| # | Claim | Status | Evidence |")
    lines.append("|---|---|---|---|")
    for c in claims:
        lines.append(f"| {c['claim_id']} | {escape(c['text'])} | {ICONS[c['status']]} {c['status']} | {escape(link_facts(c['explanation']))} |")
    lines.append("")

    questions = [c for c in claims if c["status"] != VERIFIED]
    if questions:
        lines.append("## Questions for the founder")
        lines.append("")
        for c in questions:
            lines.append(f"- {question(c)}")
        lines.append("")

    cited = sorted({fid for c in claims for fid in re.findall(r"\[(F\d+)\]", c["explanation"])}, key=lambda f: int(f[1:]))
    if cited:
        lines.append("## Evidence (every cited fact, with its receipt)")
        lines.append("")
        lines.append("| Fact | What | Value | Receipt | JSON pointer |")
        lines.append("|---|---|---|---|---|")
        for fid in cited:
            f = facts[fid]
            lines.append(f"| <a id=\"{fid.lower()}\"></a>{fid} | {escape(f['label'])} | {escape(short_value(f['value']))} | #{f['receipt_seq']} | `{f['pointer']}` |")
        lines.append("")

    lines.append("## How to check this memo")
    lines.append("")
    lines.append(f"Run `python -m receipts verify runs/{meta['run_id']}`. It recomputes the hash chain and signature, re-hashes every "
                 "stored API response, re-resolves every fact from the raw bytes, re-runs every comparison, re-renders this memo, and "
                 "(with `--witness`) checks each call against Crustdata's own usage log. No LLM is involved.")
    lines.append("")
    return "\n".join(lines)


def question(c: dict) -> str:
    status, text = c["status"], c["text"]
    if status == CONTRADICTED:
        return f"{c['claim_id']}: “{text}” conflicts with the record. Can you reconcile it?"
    if status == UNSUPPORTED:
        return f"{c['claim_id']}: “{text}” has no supporting record. Can you share evidence?"
    if status == PARTIAL:
        return f"{c['claim_id']}: “{text}” only partly matches the record. Can you clarify?"
    return f"{c['claim_id']}: “{text}” could not be checked. Please provide documentation."


def link_facts(text: str) -> str:
    return re.sub(r"\[(F\d+)\]", lambda m: f"[{m.group(1)}](#{m.group(1).lower()})", text)


def escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def short_value(value) -> str:
    if isinstance(value, list):
        return f"list of {len(value)} records"
    if isinstance(value, dict):
        name = value.get("basic_profile", {}).get("name") if "basic_profile" in value else None
        return f"profile of {name}" if name else f"object with {len(value)} fields"
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= 80 else text[:77] + "..."


# ---------------------------------------------------------------- scouting rounds and decisions

REC_ICONS = {"ADVANCE": "🟢", "PASS": "🔴", "NEEDS_HUMAN": "🟡"}


def render_round(meta: dict, candidates: list[dict], facts: dict[str, dict]) -> str:
    model = meta["model"]
    lines = [f"# Scouting round {meta['round_no']}", ""]
    lines.append(f"**Run:** `{meta['run_id']}` · as of {meta['as_of']} · model trained on {model['n_decisions']} of your decisions"
                 f" ({model['n_picks']} picks)  ")
    lines.append(f"**Predictions sealed** in ledger entry #{meta['predictions_seq']} before any human decision, so the agreement score "
                 "computed after you decide cannot be edited.  ")
    if meta.get("thesis_request"):
        tr = meta["thesis_request"]
        lines.append(f"**Thesis requested:** “{tr['text']}” (interpreted by `{tr['model']}`; every filter value validated in code)  ")
    if meta.get("thesis"):
        t = meta["thesis"]
        parts = [f"industries {', '.join(t.get('sectors', []))}", f"HQ {', '.join(t.get('hq_countries', []))}",
                 f"team {t['headcount'][0]}–{t['headcount'][1]}", f"rounds {', '.join(t.get('last_round', []))}"]
        if t.get("raised_since"):
            parts.append(f"raised since {t['raised_since']}")
        if t.get("description_keywords"):
            parts.append(f"description mentions {' or '.join(t['description_keywords'])}")
        lines.append(f"**Search filters used:** {'; '.join(parts)}  ")
    if meta.get("relaxed"):
        lines.append(f"**Relaxed to find enough companies:** {'; '.join(meta['relaxed'])}  ")
    if meta.get("thesis_request") and meta["thesis_request"].get("unmapped"):
        lines.append(f"**Not used as filters (judge these yourself):** {'; '.join(meta['thesis_request']['unmapped'])}  ")
    lines.append("")
    people = any("founders" in c["raw"] for c in candidates)
    if people:
        lines.append("| # | Company | Team | Growth YoY | Last round | Open roles (eng) | Founders (people graph) | p(you pick) | Agent | Why |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
    else:
        lines.append("| # | Company | Team | Growth YoY | Last round | Open roles (eng) | p(you pick) | Agent | Why |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
    for c in candidates:
        raw, refs = c["raw"], c["refs"]
        growth = "excluded (unstable data)" if raw.get("growth_excluded") else (
            f"{raw['growth_yoy']:+.0f}% {fref(refs, 'growth_yoy')}" if raw.get("growth_yoy") is not None else "n/a")
        team = f"{raw['headcount']:,} {fref(refs, 'headcount_total')}" if raw.get("headcount") is not None else "n/a"
        rnd = (f"{(raw.get('last_round_type') or 'n/a').replace('_', ' ')} {raw.get('last_fundraise_date') or ''} "
               f"{fref(refs, 'last_round_type')}").strip()
        roles = f"{raw.get('open_roles', 0)} ({raw.get('eng_roles', 0)}) {fref(refs, 'job_buckets')}"
        agent = f"{REC_ICONS[c['recommendation']]} {c['recommendation']}" + (" · auto" if c["auto_act"] else " · queued")
        founders_cell = f"{escape(founder_summary(raw.get('founders')))} {fref(refs, 'founders')} | " if people else ""
        lines.append(f"| {c['n']} | **{escape(c['name'])}** ({escape(c['domain'] or 'no domain')}) | {team} | {growth} | {escape(rnd)} | "
                     f"{roles} | {founders_cell}{c['probability']:.2f} | {agent} | {escape(', '.join(c['why']) or '—')} |")
    lines.append("")
    lines.append("## Why each recommendation (rule in force)")
    lines.append("")
    for c in candidates:
        lines.append(f"- **{c['n']}. {escape(c['name'])}**: {escape(c['rule'])}"
                     + (f"; missing: {', '.join(c['missing'])}" if c["missing"] else ""))
    lines.append("")
    _evidence_table(lines, facts, sorted({fid for c in candidates for fid in c["refs"].values() if fid}, key=lambda f: int(f[1:])))
    lines.append("## Your move")
    lines.append("")
    lines.append(f"Pick the companies you would take forward: `python -m receipts decide --round {meta['round_no']} --pick 2,5,7`. "
                 "Everything not picked is recorded as a reject. The agent then scores its sealed predictions against your picks "
                 "and re-fits its model of your preferences.")
    lines.append("")
    return "\n".join(lines)


def render_decision(meta: dict, decisions: list[dict], agreement: dict, learned: list[str]) -> str:
    lines = [f"# Decisions for scouting round {meta['round_no']}", ""]
    lines.append(f"**Run:** `{meta['run_id']}` · decided by a human · predictions taken from sealed run `{meta['scout_run_id']}` "
                 f"(head `{meta['scout_head_hash'][:23]}…`, signature checked before use)  ")
    lines.append("")
    lines.append("## Agent vs you")
    lines.append("")
    lines.append(f"- Agent's sealed pick/reject predictions matched **{agreement['decisions_matched']} of {agreement['total']}** of your decisions.")
    lines.append(f"- Of the agent's top {agreement['top_k']} ranked companies, you picked **{agreement['top_k_overlap']}**.")
    if agreement.get("brier") is not None:
        lines.append(f"- Calibration (Brier score): **{agreement['brier']:.3f}**; lower is better, 0.25 is what always saying 50% scores.")
    lines.append("")
    lines.append("| # | Company | Agent predicted | You decided | Agent p(pick) |")
    lines.append("|---|---|---|---|---|")
    for d in decisions:
        mark = "✅" if d["predicted_pick"] == d["picked"] else "✗"
        lines.append(f"| {d['n']} | {escape(d['name'])} | {'pick' if d['predicted_pick'] else 'reject'} | "
                     f"{'**pick**' if d['picked'] else 'reject'} {mark} | {d['probability']:.2f} |")
    lines.append("")
    lines.append("## What the agent learned about your preferences")
    lines.append("")
    for line in learned:
        lines.append(f"- {line}")
    lines.append("")
    w = meta["model_after"]["weights"]
    lines.append("| Preference | Stated thesis | Learned now |")
    lines.append("|---|---|---|")
    for f, before in meta["prior_weights"].items():
        lines.append(f"| {f.replace('_', ' ')} | {before:+.2f} | {w[f]:+.2f} |")
    lines.append("")
    return "\n".join(lines)


def founder_summary(f: dict | None) -> str:
    if not f:
        return "none listed"
    if not f["verified"]:
        return f"{f['listed']} listed, none verified at this company"
    tags = [t for t, on in (("technical", f["technical"]), ("repeat founder", f["repeat_founder"])) if on]
    if f["big_tech"]:
        tags.append("ex-" + "/".join(f["big_tech"][:3]))
    names = ", ".join(v["name"] for v in f["verified"][:3])
    return f"{names} ({len(f['verified'])} of {f['listed']} listed verified){'; ' + ', '.join(tags) if tags else ''}"


def fref(refs: dict, name: str) -> str:
    fid = refs.get(name)
    return f"[{fid}](#{fid.lower()})" if fid else ""


def _evidence_table(lines: list, facts: dict, fids: list[str]) -> None:
    if not fids:
        return
    lines.append("## Evidence (every cited fact, with its receipt)")
    lines.append("")
    lines.append("| Fact | What | Value | Receipt | JSON pointer |")
    lines.append("|---|---|---|---|---|")
    for fid in fids:
        f = facts[fid]
        lines.append(f"| <a id=\"{fid.lower()}\"></a>{fid} | {escape(f['label'])} | {escape(short_value(f['value']))} | "
                     f"#{f['receipt_seq']} | `{f['pointer']}` |")
    lines.append("")
