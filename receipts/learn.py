"""Preference learning: Bayesian logistic regression anchored on the fund's stated thesis.

- Prior: the weights in STRATEGY.md (learning.prior_weights), with strength learning.prior_strength.
  With no decisions the agent ranks exactly by the stated thesis; each pick/reject moves it.
- Fit: MAP estimate by Newton's method; weights are clipped to learning.weight_bounds.
- Uncertainty: Laplace approximation, so the agent knows when it is unsure and defers to a human.
Deterministic: the same decisions always produce the same model, so verify can re-fit it.
"""

import math

import numpy as np

from .features import DIRECTION, FEATURES, LABELS


def prior_vector(strategy: dict) -> np.ndarray:
    pw = strategy.get("learning", {}).get("prior_weights", {})
    return np.array([float(pw.get(f, 0.0)) for f in FEATURES] + [0.0])  # last entry: bias


def fit(rows: list[dict], strategy: dict) -> dict:
    """rows: [{"features": {"vector": {...}}, "label": 0|1}] -> model dict."""
    learning = strategy.get("learning", {})
    lam = float(learning.get("prior_strength", 2.0))
    lo, hi = learning.get("weight_bounds", [-3.0, 3.0])
    m = prior_vector(strategy)
    w = m.copy()
    if rows:
        X = np.array([[r["features"]["vector"][f] for f in FEATURES] + [1.0] for r in rows])
        y = np.array([r["label"] for r in rows], dtype=float)
        for _ in range(100):
            p = 1 / (1 + np.exp(-(X @ w)))
            grad = X.T @ (p - y) + lam * (w - m)
            hess = X.T @ (X * (p * (1 - p))[:, None]) + lam * np.eye(len(w))
            step = np.linalg.solve(hess, grad)
            w = w - step
            if np.max(np.abs(step)) < 1e-12:
                break
        w = np.clip(w, lo, hi)
        p = 1 / (1 + np.exp(-(X @ w)))
        hess = X.T @ (X * (p * (1 - p))[:, None]) + lam * np.eye(len(w))
    else:
        hess = lam * np.eye(len(w))
    sigma = np.linalg.inv(hess)
    return {
        "features": FEATURES,
        "weights": {f: round(float(w[i]), 6) for i, f in enumerate(FEATURES)},
        "bias": round(float(w[-1]), 6),
        "covariance": [[round(float(c), 9) for c in row] for row in sigma],
        "n_decisions": len(rows),
        "n_picks": int(sum(r["label"] for r in rows)),
    }


def predict(model: dict, vector: dict) -> dict:
    x = np.array([vector[f] for f in FEATURES] + [1.0])
    w = np.array([model["weights"][f] for f in FEATURES] + [model["bias"]])
    sigma = np.array(model["covariance"])
    mu = float(x @ w)
    var = float(x @ sigma @ x)
    p = 1 / (1 + math.exp(-mu / math.sqrt(1 + math.pi * var / 8)))
    contributions = sorted(((f, round(model["weights"][f] * vector[f], 4)) for f in FEATURES), key=lambda t: -abs(t[1]))
    return {"probability": round(p, 4), "confidence": round(max(p, 1 - p), 4), "contributions": contributions}


def learned_summary(strategy: dict, model: dict, rows: list[dict]) -> list[str]:
    """Plain-language statements derived only from the fitted weights and the decision data."""
    if not rows:
        return ["No decisions yet: ranking purely by the stated thesis in STRATEGY.md."]
    prior = strategy.get("learning", {}).get("prior_weights", {})
    picks = [r for r in rows if r["label"] == 1]
    rejects = [r for r in rows if r["label"] == 0]
    lines = [f"Learned from {len(rows)} decisions ({len(picks)} picks, {len(rejects)} rejects)."]
    shifts = sorted(FEATURES, key=lambda f: -abs(model["weights"][f] - float(prior.get(f, 0.0))))
    hidden = 0
    for f in shifts:
        before, after = float(prior.get(f, 0.0)), model["weights"][f]
        if abs(after - before) < 0.15:
            continue
        a, b = _medians(f, picks), _medians(f, rejects)
        # Only state a preference when the raw data points the same way as the learned shift. Features are
        # correlated, so a weight can move against the raw medians; saying so in words would mislead.
        if a is not None and b is not None and (a == b or (a > b) != (after > before)):
            hidden += 1
            continue
        lean = DIRECTION[f][0] if after > before else DIRECTION[f][1]
        evidence = f": median {_fmt(f, a)} for your picks vs {_fmt(f, b)} for rejects" if a is not None and b is not None else ""
        lines.append(f"Your decisions lean toward {lean} more than the stated thesis did "
                     f"({LABELS[f]}: weight {before:+.2f} → {after:+.2f}){evidence}.")
    if hidden:
        lines.append(f"{hidden} smaller adjustment{'s are' if hidden > 1 else ' is'} not described because your raw picks don't clearly "
                     "show it on their own (they come from how features combine).")
    if len(lines) == 1:
        lines.append("Your decisions so far match the stated thesis; no preference has shifted noticeably.")
    return lines


def _medians(feature: str, rows: list[dict]):
    vals = sorted(r["features"]["raw"].get(feature) for r in rows if r["features"]["raw"].get(feature) is not None)
    return vals[len(vals) // 2] if vals else None


def _evidence(feature: str, picks: list[dict], rejects: list[dict]) -> str:
    def median(rows):
        vals = sorted(r["features"]["raw"].get(feature) for r in rows if r["features"]["raw"].get(feature) is not None)
        return vals[len(vals) // 2] if vals else None
    a, b = median(picks), median(rejects)
    if a is None or b is None or _fmt(feature, a) == _fmt(feature, b):
        return ""
    return f": median {_fmt(feature, a)} for your picks vs {_fmt(feature, b)} for rejects"


def _fmt(feature: str, value) -> str:
    if feature == "growth_yoy":
        return f"{value:+.0f}%"
    if feature == "eng_hiring_share":
        return f"{value * 100:.0f}%"
    if feature == "total_funding":
        return f"${value / 1e6:,.0f}M"
    if feature == "months_since_round":
        return f"{value:.0f} month{'s' if round(value) != 1 else ''}"
    if feature == "company_age":
        return f"{value} years"
    return f"{value:,}" if isinstance(value, int) else str(value)


def agreement(predictions: list[dict], picked_ids: set[int]) -> dict:
    """Compare the sealed predictions with the human's picks."""
    total = len(predictions)
    same = sum(1 for p in predictions if p["predicted_pick"] == (p["company_id"] in picked_ids))
    k = len(picked_ids)
    top_k = [p["company_id"] for p in sorted(predictions, key=lambda p: -p["probability"])[:k]]
    overlap = len(set(top_k) & picked_ids)
    brier = round(sum((p["probability"] - (1.0 if p["company_id"] in picked_ids else 0.0)) ** 2 for p in predictions) / total, 4) if total else None
    return {"decisions_matched": same, "total": total, "accuracy": round(same / total, 3) if total else None,
            "top_k": k, "top_k_overlap": overlap, "brier": brier}
