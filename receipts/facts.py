"""Facts: values pulled out of a receipt by JSON Pointer (RFC 6901).

The LLM and the report only ever cite fact IDs (F1, F2, ...); code owns the pointers,
so every value in the memo can be re-resolved from the raw response blob.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import jsonpointer

from .proxy import Receipt

_MISSING = object()


@dataclass
class Fact:
    id: str
    receipt_seq: int
    pointer: str
    value: object
    label: str


class FactStore:
    def __init__(self):
        self.facts: dict[str, Fact] = {}

    def add(self, receipt: Receipt, pointer: str, label: str) -> Fact | None:
        """Register the value at `pointer` in the receipt; None when the field is absent or null."""
        value = resolve(receipt.data, pointer)
        if value is _MISSING or value is None:
            return None
        fact = Fact(id=f"F{len(self.facts) + 1}", receipt_seq=receipt.seq, pointer=pointer, value=value, label=label)
        self.facts[fact.id] = fact
        return fact

    def value(self, fact_id: str):
        return self.facts[fact_id].value

    def save(self, path: Path) -> None:
        path.write_text(json.dumps([asdict(f) for f in self.facts.values()], indent=1, ensure_ascii=False), encoding="utf-8")


def resolve(data, pointer: str):
    try:
        return jsonpointer.resolve_pointer(data, pointer)
    except (jsonpointer.JsonPointerException, KeyError, IndexError, TypeError):
        return _MISSING


def load_facts(path: Path) -> dict[str, dict]:
    return {f["id"]: f for f in json.loads(path.read_text(encoding="utf-8"))}
