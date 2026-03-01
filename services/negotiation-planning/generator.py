from __future__ import annotations

from typing import Any


SEVERITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}
DEFAULT_CONCESSION_PACKAGES: tuple[tuple[str, str], ...] = (
    (
        "Hold firm on scope and base while offering flexible start-date timing.",
        "Written scope alignment and a six-month compensation review checkpoint.",
    ),
    (
        "Reduce base ask slightly in exchange for near-term upside.",
        "Sign-on bonus coverage or guaranteed equity refresh timing.",
    ),
    (
        "Accept floor compensation only with explicit growth guarantees.",
        "Promotion criteria, level rubric, and review timeline in writing.",
    ),
)


class DeterministicNegotiationStrategyGenerator:
    """Deterministic strategy synthesis from negotiation context signals."""

    def generate(
        self,
        *,
        target_role: str,
        compensation_targets: dict[str, Any],
        leverage_signals: list[dict[str, Any]],
        risk_signals: list[dict[str, Any]],
        evidence_links: list[dict[str, str]],
    ) -> dict[str, Any]:
        normalized_compensation = _normalize_compensation_targets(compensation_targets)
        normalized_leverage = _normalize_leverage_signals(leverage_signals)
        normalized_risk = _normalize_risk_signals(risk_signals)
        normalized_evidence = _normalize_evidence_links(evidence_links)

        anchor_band = _build_anchor_band(
            target_role=target_role,
            compensation_targets=normalized_compensation,
            leverage_signals=normalized_leverage,
            risk_signals=normalized_risk,
        )
        concession_ladder = _build_concession_ladder(
            anchor_band=anchor_band,
            leverage_signals=normalized_leverage,
            risk_signals=normalized_risk,
            evidence_links=normalized_evidence,
        )
        objection_playbook = _build_objection_playbook(
            anchor_band=anchor_band,
            leverage_signals=normalized_leverage,
            risk_signals=normalized_risk,
            evidence_links=normalized_evidence,
        )
        talking_points = _build_talking_points(
            target_role=target_role,
            anchor_band=anchor_band,
            leverage_signals=normalized_leverage,
            risk_signals=normalized_risk,
            concession_ladder=concession_ladder,
        )

        lead_leverage = _label_signal(normalized_leverage[0].get("signal", "trajectory_readiness"))
        lead_risk = _label_signal(normalized_risk[0].get("signal", "deadline_pressure"))
        strategy_summary = (
            f"Anchor near {anchor_band['ceiling_base_salary']} with {lead_leverage} evidence, "
            f"protect {anchor_band['floor_base_salary']} as walk-away floor, and pre-handle {lead_risk} objections."
        )

        return {
            "strategy_summary": strategy_summary,
            "anchor_band": anchor_band,
            "concession_ladder": concession_ladder,
            "objection_playbook": objection_playbook,
            "talking_points": talking_points,
        }


def _normalize_compensation_targets(raw: dict[str, Any]) -> dict[str, Any]:
    currency = str(raw.get("currency", "USD")).strip().upper() or "USD"
    current_base = _coerce_nonnegative_int(raw.get("current_base_salary"), default=150000)
    target_base = _coerce_nonnegative_int(raw.get("target_base_salary"), default=max(current_base, 165000))
    ceiling = _coerce_nonnegative_int(raw.get("anchor_base_salary"), default=max(target_base, current_base + 10000))
    floor = _coerce_nonnegative_int(raw.get("walk_away_base_salary"), default=max(0, min(target_base, current_base)))
    counter = _coerce_nonnegative_int(raw.get("recommended_counter_base_salary"), default=target_base)

    if floor > ceiling:
        floor = ceiling
    counter = max(floor, min(counter, ceiling))
    target_base = max(floor, min(target_base, ceiling))

    return {
        "currency": currency,
        "current_base_salary": current_base,
        "target_base_salary": target_base,
        "anchor_base_salary": ceiling,
        "walk_away_base_salary": floor,
        "recommended_counter_base_salary": counter,
    }


def _normalize_leverage_signals(raw_signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in raw_signals:
        if not isinstance(raw, dict):
            continue
        signal = str(raw.get("signal", "")).strip()
        evidence = str(raw.get("evidence", "")).strip()
        score = _coerce_score(raw.get("score"), default=60.0)
        if not signal or not evidence:
            continue
        normalized.append(
            {
                "signal": signal,
                "score": score,
                "evidence": evidence,
            }
        )
    normalized.sort(key=lambda item: (-float(item["score"]), str(item["signal"])))
    if normalized:
        return normalized
    return [
        {
            "signal": "trajectory_readiness",
            "score": 62.0,
            "evidence": "Readiness baseline supports compensation rationale.",
        }
    ]


def _normalize_risk_signals(raw_signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in raw_signals:
        if not isinstance(raw, dict):
            continue
        signal = str(raw.get("signal", "")).strip()
        evidence = str(raw.get("evidence", "")).strip()
        severity = str(raw.get("severity", "")).strip().lower()
        if severity not in SEVERITY_RANK:
            continue
        score = _coerce_score(raw.get("score"), default=45.0)
        if not signal or not evidence:
            continue
        normalized.append(
            {
                "signal": signal,
                "severity": severity,
                "score": score,
                "evidence": evidence,
            }
        )
    normalized.sort(
        key=lambda item: (
            -SEVERITY_RANK[str(item["severity"])],
            -float(item["score"]),
            str(item["signal"]),
        )
    )
    if normalized:
        return normalized
    return [
        {
            "signal": "deadline_pressure",
            "severity": "medium",
            "score": 45.0,
            "evidence": "Timeline ambiguity may compress negotiation windows.",
        }
    ]


def _normalize_evidence_links(raw_links: list[dict[str, str]]) -> list[dict[str, str]]:
    order = {
        "offer_input": 0,
        "candidate_profile": 1,
        "interview_session": 2,
        "feedback_report": 3,
        "trajectory_plan": 4,
    }
    normalized: list[dict[str, str]] = []
    for raw in raw_links:
        if not isinstance(raw, dict):
            continue
        source_type = str(raw.get("source_type", "")).strip()
        source_id = str(raw.get("source_id", "")).strip()
        detail = str(raw.get("detail", "")).strip()
        if not source_type or not source_id or not detail:
            continue
        normalized.append(
            {
                "source_type": source_type,
                "source_id": source_id,
                "detail": detail,
            }
        )
    normalized.sort(
        key=lambda item: (
            order.get(str(item["source_type"]), 99),
            str(item["source_id"]),
            str(item["detail"]),
        )
    )
    if normalized:
        return normalized
    return [
        {
            "source_type": "offer_input",
            "source_id": "candidate",
            "detail": "Offer context baseline evidence.",
        }
    ]


def _build_anchor_band(
    *,
    target_role: str,
    compensation_targets: dict[str, Any],
    leverage_signals: list[dict[str, Any]],
    risk_signals: list[dict[str, Any]],
) -> dict[str, Any]:
    floor = int(compensation_targets["walk_away_base_salary"])
    target = int(compensation_targets["recommended_counter_base_salary"])
    ceiling = int(compensation_targets["anchor_base_salary"])
    currency = str(compensation_targets["currency"])

    target = max(floor, min(target, ceiling))
    if ceiling < target:
        ceiling = target

    lead_leverage = _label_signal(leverage_signals[0]["signal"])
    lead_risk = _label_signal(risk_signals[0]["signal"])
    role_label = str(target_role).strip() or "target role"
    rationale = (
        f"Band aligns to {role_label} scope: start at {ceiling}, settle near {target}, "
        f"and hold {floor} floor using {lead_leverage} evidence while managing {lead_risk}."
    )

    return {
        "currency": currency,
        "floor_base_salary": floor,
        "target_base_salary": target,
        "ceiling_base_salary": ceiling,
        "rationale": rationale,
    }


def _build_concession_ladder(
    *,
    anchor_band: dict[str, Any],
    leverage_signals: list[dict[str, Any]],
    risk_signals: list[dict[str, Any]],
    evidence_links: list[dict[str, str]],
) -> list[dict[str, Any]]:
    floor = int(anchor_band["floor_base_salary"])
    target = int(anchor_band["target_base_salary"])
    ceiling = int(anchor_band["ceiling_base_salary"])
    span = max(0, ceiling - floor)

    midpoint = _round_to_500(max(target, ceiling - int(round(span * 0.45))))
    asks = [ceiling, midpoint, max(floor, target)]
    asks = _dedupe_preserve_order(asks)
    if len(asks) < 3 and floor not in asks:
        asks.append(floor)
    if len(asks) == 1:
        asks.append(floor)

    ladder: list[dict[str, Any]] = []
    for index, ask in enumerate(asks):
        package = DEFAULT_CONCESSION_PACKAGES[min(index, len(DEFAULT_CONCESSION_PACKAGES) - 1)]
        risk = risk_signals[min(index, len(risk_signals) - 1)]
        leverage = leverage_signals[min(index, len(leverage_signals) - 1)]
        evidence = evidence_links[min(index, len(evidence_links) - 1)]
        ladder.append(
            {
                "step": index + 1,
                "ask_base_salary": int(max(floor, min(ask, ceiling))),
                "trigger": f"If employer raises {_label_signal(risk['signal'])} pushback.",
                "concession": package[0],
                "exchange_for": package[1],
                "evidence": (
                    f"{leverage['evidence']} Source {evidence['source_type']}:{evidence['source_id']}."
                ),
            }
        )

    ladder.sort(key=lambda item: int(item["step"]))
    return ladder


def _build_objection_playbook(
    *,
    anchor_band: dict[str, Any],
    leverage_signals: list[dict[str, Any]],
    risk_signals: list[dict[str, Any]],
    evidence_links: list[dict[str, str]],
) -> list[dict[str, Any]]:
    top_risks = risk_signals[:3]
    playbook: list[dict[str, Any]] = []
    for index, risk in enumerate(top_risks):
        leverage = leverage_signals[min(index, len(leverage_signals) - 1)]
        evidence = evidence_links[min(index, len(evidence_links) - 1)]
        playbook.append(
            {
                "risk_signal": str(risk["signal"]),
                "objection": _objection_prompt(str(risk["signal"])),
                "response": (
                    f"Acknowledge the concern, tie ask to {_label_signal(leverage['signal'])} outcomes, "
                    f"and keep counter near {anchor_band['target_base_salary']}."
                ),
                "evidence": (
                    f"{risk['evidence']} Supporting source {evidence['source_type']}:{evidence['source_id']}."
                ),
                "fallback_trade": _fallback_trade(index),
            }
        )

    if playbook:
        return playbook
    return [
        {
            "risk_signal": "deadline_pressure",
            "objection": "We need a quick yes/no decision.",
            "response": "Confirm decision timeline and hold target compensation with clear trade-offs.",
            "evidence": "Timeline pressure managed with explicit next-step commitments.",
            "fallback_trade": _fallback_trade(0),
        }
    ]


def _build_talking_points(
    *,
    target_role: str,
    anchor_band: dict[str, Any],
    leverage_signals: list[dict[str, Any]],
    risk_signals: list[dict[str, Any]],
    concession_ladder: list[dict[str, Any]],
) -> list[str]:
    role_label = str(target_role).strip() or "target role"
    lead_leverage = leverage_signals[0]
    lead_risk = risk_signals[0]
    step_two = concession_ladder[1] if len(concession_ladder) > 1 else concession_ladder[0]

    return [
        (
            f"Open with {role_label} impact evidence and anchor at "
            f"{anchor_band['ceiling_base_salary']}."
        ),
        (
            f"Reinforce {_label_signal(lead_leverage['signal'])} with concrete outcomes before discussing trade-offs."
        ),
        (
            f"If {_label_signal(lead_risk['signal'])} appears, move to step {step_two['step']} "
            f"at {step_two['ask_base_salary']} only in exchange for explicit commitments."
        ),
    ]


def _objection_prompt(signal: str) -> str:
    mapping = {
        "deadline_pressure": "We need an answer quickly and cannot re-open compensation.",
        "compensation_compression": "Your ask is above our planned salary band.",
        "trajectory_gap": "We need stronger proof for this level or scope.",
        "momentum_volatility": "We need more consistency before increasing the package.",
    }
    return mapping.get(signal, "We cannot move on compensation right now.")


def _fallback_trade(index: int) -> str:
    fallback = (
        "Ask for scope alignment, review timing, or non-base compensation movement if base is fixed.",
        "Prioritize sign-on bonus or equity refresh with documented timeline.",
        "Confirm written level criteria and promotion review trigger.",
    )
    return fallback[min(index, len(fallback) - 1)]


def _label_signal(signal: str) -> str:
    return str(signal).replace("_", " ").strip() or "negotiation context"


def _coerce_nonnegative_int(raw_value: Any, *, default: int) -> int:
    if not isinstance(raw_value, int) or isinstance(raw_value, bool):
        return int(default)
    if raw_value < 0:
        return int(default)
    return int(raw_value)


def _coerce_score(raw_value: Any, *, default: float) -> float:
    if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
        return round(float(default), 2)
    score = float(raw_value)
    if 0.0 <= score <= 1.0:
        score *= 100.0
    return round(max(0.0, min(100.0, score)), 2)


def _round_to_500(raw_value: int) -> int:
    return int(round(float(raw_value) / 500.0) * 500)


def _dedupe_preserve_order(values: list[int]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for value in values:
        normalized = int(value)
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered
