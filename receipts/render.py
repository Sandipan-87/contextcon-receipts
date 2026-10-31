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
