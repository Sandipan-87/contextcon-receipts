"""Drafted emails. The LLM may word them, but every number it writes must come from the facts
given to it; otherwise the deterministic template is used. Drafts are never sent."""

import re

from . import llm, trace

SYSTEM = ("You draft short, professional emails for a venture fund analyst. Use ONLY the facts provided; "
          "never add numbers, names or claims that are not in the facts. No subject line, no signature placeholders "
          "other than '[Analyst name]'. Plain text, under 140 words.")


def grounded(text: str, facts_text: str) -> bool:
    allowed = set(_numbers(facts_text))
    return all(n in allowed for n in _numbers(text))


def _numbers(text: str) -> list[str]:
    return [n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


def draft(kind: str, company: str, facts_lines: list[str], template: str) -> tuple[str, str]:
    """Returns (body, author) where author is 'llm:<model>' or 'template'."""
    facts_text = "\n".join(f"- {line}" for line in facts_lines)
    if llm.available():
        try:
            body, model = llm.chat_text(SYSTEM, f"Email type: {kind}\nCompany: {company}\nFacts:\n{facts_text}\n\nWrite the email body.")
            body = body.strip()
            if body and grounded(body, facts_text + "\n" + company):
                return body, f"llm:ollama/{model}"
            trace.warn("drafted email contained numbers not in the facts; using the deterministic template")
        except Exception as exc:
            trace.warn(f"LLM email draft failed ({exc.__class__.__name__}); using the deterministic template")
    return template, "template"
