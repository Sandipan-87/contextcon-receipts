"""Load the fund's rulebook (strategy/STRATEGY.md) and enforce its action permissions."""

import re
from pathlib import Path

import yaml

from .config import ROOT

STRATEGY_PATH = ROOT / "strategy" / "STRATEGY.md"


class ActionNotAllowed(Exception):
    pass


def load_strategy(path: Path = STRATEGY_PATH) -> tuple[dict, str]:
    """Returns (parsed rules, full file text). The text is sealed into each run's ledger."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"```yaml\n(.*?)```", text, re.S)
    if not m:
        raise ValueError(f"{path} has no ```yaml block")
    return yaml.safe_load(m.group(1)), text


def check_action(strategy: dict, action: str) -> str:
    """Raise unless the rulebook allows this action; return the rule that allows it."""
    actions = strategy.get("actions", {})
    if action in actions.get("forbidden", []):
        raise ActionNotAllowed(f"action {action!r} is forbidden by actions.forbidden")
    if action not in actions.get("allowed", []):
        raise ActionNotAllowed(f"action {action!r} is not in actions.allowed")
    return f"actions.allowed contains {action!r}"
