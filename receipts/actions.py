"""Executes the agent's final actions, only when the rulebook allows them.

Each action is checked against strategy actions.allowed/forbidden, executed, and recorded in the
run's ledger with the rule that permitted it. Emails are drafted to outbox/ and never sent
(handbook rule 4: no interaction with external real people).
"""

import re

from . import board, trace
from .ledger import Ledger, sha256_hex
from .strategy import ActionNotAllowed, check_action


class ActionRunner:
    def __init__(self, ledger: Ledger, strategy: dict, run_id: str):
        self.ledger, self.strategy, self.run_id = ledger, strategy, run_id
        self.conn = board.connect()
        self.executed = []

    def _record(self, action: str, company_id, detail: dict, because: str) -> bool:
        try:
            rule = check_action(self.strategy, action)
        except ActionNotAllowed as exc:
            self.ledger.append("action_blocked", {"action": action, "company_id": company_id, "reason": str(exc)})
            trace.bad(f"blocked {action}: {exc}")
            return False
        self.ledger.append("action", {"action": action, "company_id": company_id, "allowed_by": rule,
                                      "because": because, **detail})
        self.executed.append({"action": action, "company_id": company_id, **detail})
        return True

    def update_board(self, company_id: int, because: str, **fields) -> None:
        if self._record("update_deal_board", company_id, {"fields": {k: v for k, v in fields.items() if k != "features"}}, because):
            board.upsert(self.conn, company_id, self.run_id, **fields)
            board.log_event(self.conn, company_id, self.run_id, "board_update", f"{fields.get('stage')} · {because}")
            trace.info(f"  [action] deal board: {fields.get('name') or company_id} → {fields.get('stage')}")

    def draft_email(self, company_id: int, name: str, subject: str, body: str, because: str,
                    author: str = "template", grounding_facts: list[str] | None = None) -> None:
        board.OUTBOX.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", (name or str(company_id)).lower()).strip("-")[:40]
        path = board.OUTBOX / f"{self.run_id}_{slug}.eml"
        eml = (f"X-Receipts-Status: DRAFT - NOT SENT (handbook rule 4: no contact with external people)\n"
               f"X-Receipts-Run: {self.run_id}\nTo: founders of {name} <address to be added by the analyst>\n"
               f"Subject: {subject}\nContent-Type: text/plain; charset=utf-8\n\n{body}\n")
        if self._record("draft_email_to_outbox", company_id,
                        {"path": f"outbox/{path.name}", "subject": subject, "author": author, "body": body,
                         "grounding_facts": grounding_facts or [], "eml_hash": sha256_hex(eml.encode("utf-8"))}, because):
            path.write_text(eml, encoding="utf-8")
            board.log_event(self.conn, company_id, self.run_id, "email_drafted", f"outbox/{path.name}")
            trace.info(f"  [action] drafted email (not sent): outbox/{path.name}")

    def try_forbidden_send(self, company_id: int) -> None:
        """Demonstrates the guardrail: sending is not permitted, so it is blocked and logged."""
        self._record("send_external_email", company_id, {}, "attempted only to demonstrate the guardrail")
