"""Turn a pitch's claim verdicts into a decision (hard rules from STRATEGY.md) and act on it."""

import re

from . import trace
from .actions import ActionRunner
from .claims import CONTRADICTED, UNSUPPORTED, VERIFIED
from .compose import draft

FACT_TAG = re.compile(r" ?\[F\d+\]")
STAGE_FOR = {"ADVANCE": "Partner meeting", "REQUEST_INFO": "Awaiting founder info", "PASS": "Passed", "NEEDS_HUMAN": "Needs analyst"}


def pitch_decision(results: list[dict], resolution, strategy: dict) -> dict:
    guard = strategy.get("guardrails", {})
    contradicted = [c for c in results if c["status"] == CONTRADICTED]
    unsupported = [c for c in results if c["status"] == UNSUPPORTED]
    limit = guard.get("pass_if_contradictions", 3)
    if resolution.status != "RESOLVED":
        return {"decision": "NEEDS_HUMAN", "rule": f"guardrails.ambiguous_entity: company is {resolution.status}; the agent never guesses"}
    if len(contradicted) >= limit:
        return {"decision": "PASS", "rule": f"guardrails.pass_if_contradictions: {len(contradicted)} contradicted claims (limit {limit})"}
    if contradicted or unsupported:
        ids = ", ".join(c["claim_id"] for c in contradicted + unsupported)
        return {"decision": "REQUEST_INFO",
                "rule": f"guardrails.block_advance_if_contradicted: claims {ids} conflict with or lack a record, "
                        "so the agent cannot advance and asks the founder instead"}
    return {"decision": "ADVANCE", "rule": "no contradicted or unsupported claims; every checkable claim is consistent with the record"}


def act_on_pitch(ledger, strategy, run_id, decision, resolution, results) -> None:
    trace.step("Acting within the rulebook")
    if resolution.status != "RESOLVED":
        trace.info("  no company ID, so nothing goes on the deal board; flagged for an analyst in the ledger")
        return
    runner = ActionRunner(ledger, strategy, run_id)
    because = f"pitch decision {decision['decision']}: {decision['rule']}"
    runner.update_board(resolution.company_id, because, name=resolution.name, domain=resolution.domain, source="pitch",
                        stage=STAGE_FOR[decision["decision"]], agent_recommendation=decision["decision"])
    name = resolution.name
    issues = [c for c in results if c["status"] != VERIFIED]
    facts_lines = []
    for c in issues:
        check = FACT_TAG.sub("", c["explanation"])
        facts_lines.append(f"{c['claim_id']}: you wrote \"{c['text']}\"; our check: {check}")

    if decision["decision"] == "REQUEST_INFO":
        bullet_list = "\n".join(f"- {line}" for line in facts_lines)
        template = (f"Hi {name} team,\n\nThank you for sending your pitch. Before we take it to our partners, we would like "
                    f"to reconcile a few points with the public record:\n\n{bullet_list}\n\n"
                    "Could you share documentation or clarify these?\n\nBest,\n[Analyst name]")
        body, author = draft("follow-up questions to the founders about claims that did not match the record",
                             name, facts_lines, template)
        runner.draft_email(resolution.company_id, name, f"{name}: a few questions before our partner review",
                           body, because, author, facts_lines)
    elif decision["decision"] == "PASS":
        template = (f"Hi {name} team,\n\nThank you for sharing your pitch. After review we will not be moving forward at "
                    "this time. We wish you the very best and would be glad to stay in touch.\n\nBest,\n[Analyst name]")
        runner.draft_email(resolution.company_id, name, f"{name}: thank you", template, because, "template", [])
    elif decision["decision"] == "ADVANCE":
        template = (f"Hi {name} team,\n\nThank you for your pitch. We would love to set up a call with our partners in the "
                    "next two weeks.\n\nBest,\n[Analyst name]")
        runner.draft_email(resolution.company_id, name, f"{name}: next step with our partners", template, because, "template", [])
