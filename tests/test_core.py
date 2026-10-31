"""Offline tests (no API calls). The learner test uses SYNTHETIC decisions generated in memory,
never written to the real deal board, to check that the model can recover a hidden preference."""

import json
import random

from receipts import learn
from receipts.claims import CONTRADICTED, PARTIAL, UNVERIFIABLE, VERIFIED, evaluate
from receipts.features import FEATURES
from receipts.ledger import Ledger, entry_hash, read_ledger, verify_signature
from receipts.strategy import ActionNotAllowed, check_action, load_strategy

STRATEGY, _ = load_strategy()


def test_ledger_detects_edit(tmp_path):
    ledger = Ledger(tmp_path, "t1")
    ledger.append("note", {"x": 1})
    ledger.append("note", {"x": 2})
    sealed = ledger.seal()
    assert verify_signature(sealed)
    entries = read_ledger(tmp_path)
    assert all(entry_hash(e) == e["entry_hash"] for e in entries)
    entries[1]["x"] = 99
    assert entry_hash(entries[1]) != entries[1]["entry_hash"]


def test_tolerances_come_from_strategy():
    inputs = {"headcount_total": 1000, "timeseries": None}
    refs = {"headcount_total": "F1"}
    assert evaluate("headcount", {"value": 1100}, inputs, refs, {"headcount": {"verified": 15, "partial": 40}})[0] == VERIFIED
    assert evaluate("headcount", {"value": 1100}, inputs, refs, {"headcount": {"verified": 5, "partial": 40}})[0] == PARTIAL
    assert evaluate("headcount", {"value": 3000}, inputs, refs, {})[0] == CONTRADICTED


def test_unstable_series_is_never_a_contradiction():
    series = [{"date": "2026-09-02", "employee_count": 11703}, {"date": "2026-09-11", "employee_count": 5935},
              {"date": "2026-10-15", "employee_count": 2900}]
    status, why = evaluate("headcount", {"value": 3700}, {"headcount_total": 3757, "timeseries": series}, {"headcount_total": "F1"})
    assert status == UNVERIFIABLE and "unstable" in why


def test_forbidden_actions_are_blocked():
    assert "update_deal_board" in check_action(STRATEGY, "update_deal_board")
    for action in ("send_external_email", "launch_rockets"):
        try:
            check_action(STRATEGY, action)
            raise AssertionError("should have been blocked")
        except ActionNotAllowed:
            pass


def test_learner_recovers_hidden_preference_synthetic():
    """SYNTHETIC: a simulated analyst who strongly prefers high growth and small teams."""
    rng = random.Random(7)

    def company():
        return {f: max(-3.0, min(3.0, rng.gauss(0, 1))) for f in FEATURES}

    def simulated_pick(v):
        return 1 if 1.5 * v["growth_yoy"] - 1.2 * v["headcount"] + rng.gauss(0, 0.3) > 0 else 0

    history, scores = [], []
    for round_no in range(5):
        batch = [company() for _ in range(10)]
        model = learn.fit(history, STRATEGY)
        preds = [{"company_id": i, "probability": learn.predict(model, v)["probability"],
                  "predicted_pick": learn.predict(model, v)["probability"] >= 0.5} for i, v in enumerate(batch)]
        picks = {i for i, v in enumerate(batch) if simulated_pick(v)}
        scores.append(learn.agreement(preds, picks)["accuracy"])
        history += [{"features": {"vector": v, "raw": {}}, "label": int(i in picks)} for i, v in enumerate(batch)]
    final = learn.fit(history, STRATEGY)
    assert final["weights"]["growth_yoy"] > 0.8 and final["weights"]["headcount"] < -0.2
    assert sum(scores[-2:]) / 2 >= scores[0]
    print("synthetic agreement by round:", scores)


def test_fit_is_deterministic():
    rows = [{"features": {"vector": {f: (i % 3 - 1) * 0.5 for f in FEATURES}}, "label": i % 2} for i in range(12)]
    assert json.dumps(learn.fit(rows, STRATEGY)) == json.dumps(learn.fit(rows, STRATEGY))
