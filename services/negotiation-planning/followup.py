from __future__ import annotations

from typing import Any


SEVERITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}


class DeterministicNegotiationFollowupPlanner:
    """Deterministic follow-up planner for post-negotiation execution."""

    def generate(
        self,
        *,
        target_role: str,
        strategy_summary: str,
        anchor_band: dict[str, Any],
        concession_ladder: list[dict[str, Any]],
        leverage_signals: list[dict[str, Any]],
        risk_signals: list[dict[str, Any]],
        evidence_links: list[dict[str, str]],
    ) -> dict[str, Any]:
        role_label = str(target_role).strip() or "target role"
        normalized_leverage = _normalize_leverage_signals(leverage_signals)
        normalized_risks = _normalize_risk_signals(risk_signals)
        normalized_evidence = _normalize_evidence_links(evidence_links)
        normalized_anchor = _normalize_anchor_band(anchor_band)
        cadence_offsets = _derive_cadence_offsets(normalized_risks)

        lead_leverage = _signal_label(normalized_leverage[0].get("signal", "trajectory_readiness"))
        lead_risk = _signal_label(normalized_risks[0].get("signal", "deadline_pressure"))
        target_salary = int(normalized_anchor["target_base_salary"])
        currency = str(normalized_anchor["currency"])
        strategy_line = _first_sentence(strategy_summary) or (
            f"Anchor around {currency} {target_salary:,} while preserving scope and review commitments."
        )

        thank_you_note = {
            "send_by_day_offset": 0,
            "subject": f"Thank you - {role_label} discussion follow-up",
            "body": (
                f"Thank you for the discussion about the {role_label} opportunity. {strategy_line} "
                f"I remain excited about the role and confident in the outcomes I can deliver."
            ),
            "key_points": [
                f"Reinforce {lead_leverage} evidence tied to role outcomes.",
                f"Reference target compensation rationale around {currency} {target_salary:,}.",
                f"Address {lead_risk} concerns with a concrete decision timeline.",
            ],
        }

        cadence_channels = _cadence_channels_for_risk(normalized_risks)
        cadence_templates = _cadence_templates(
            role_label=role_label,
            target_salary=target_salary,
            lead_leverage=lead_leverage,
            lead_risk=lead_risk,
            evidence=normalized_evidence[0]["detail"],
        )
        recruiter_cadence: list[dict[str, Any]] = []
        for index, day_offset in enumerate(cadence_offsets):
            template = cadence_templates[min(index, len(cadence_templates) - 1)]
            channel = cadence_channels[min(index, len(cadence_channels) - 1)]
            recruiter_cadence.append(
                {
                    "day_offset": int(day_offset),
                    "channel": channel,
                    "objective": template["objective"],
                    "message": template["message"],
                }
            )

        max_cadence_day = max(cadence_offsets) if cadence_offsets else 5
        branch_sequences = _outcome_branch_sequences(max_cadence_day=max_cadence_day, risks=normalized_risks)
        outcome_branches: list[dict[str, Any]] = []
        for branch in branch_sequences:
            actions = [
                {
                    "day_offset": int(item["day_offset"]),
                    "action": str(item["action"]),
                }
                for item in branch["actions"]
            ]
            outcome_branches.append(
                {
                    "outcome": str(branch["outcome"]),
                    "actions": actions,
                }
            )

        follow_up_actions = [
            {
                "day_offset": int(item["day_offset"]),
                "action": f"{item['objective']}. {item['message']}",
            }
            for item in recruiter_cadence
        ]
        if concession_ladder:
            first_ladder = concession_ladder[0]
            if isinstance(first_ladder, dict):
                follow_up_actions.append(
                    {
                        "day_offset": min(7, max_cadence_day + 1),
                        "action": (
                            f"Prepare fallback concession package from step {int(first_ladder.get('step', 1))} "
                            f"before next negotiation checkpoint."
                        ),
                    }
                )

        follow_up_actions.sort(key=lambda item: (int(item["day_offset"]), str(item["action"])))

        return {
            "follow_up_plan": {
                "thank_you_note": thank_you_note,
                "recruiter_cadence": recruiter_cadence,
                "outcome_branches": outcome_branches,
            },
            "follow_up_actions": follow_up_actions,
        }


def _normalize_anchor_band(raw_anchor_band: dict[str, Any]) -> dict[str, Any]:
    currency = str(raw_anchor_band.get("currency", "USD")).strip().upper() or "USD"
    floor = _coerce_nonnegative_int(raw_anchor_band.get("floor_base_salary"), default=0)
    target = _coerce_nonnegative_int(raw_anchor_band.get("target_base_salary"), default=floor)
    ceiling = _coerce_nonnegative_int(raw_anchor_band.get("ceiling_base_salary"), default=max(floor, target))
    target = max(floor, min(target, ceiling))
    return {
        "currency": currency,
        "floor_base_salary": floor,
        "target_base_salary": target,
        "ceiling_base_salary": max(target, ceiling),
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
        normalized.append({"signal": signal, "score": score, "evidence": evidence})
    normalized.sort(key=lambda item: (-float(item["score"]), str(item["signal"])))
    if normalized:
        return normalized
    return [{"signal": "trajectory_readiness", "score": 62.0, "evidence": "Readiness baseline supports value messaging."}]


def _normalize_risk_signals(raw_signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in raw_signals:
        if not isinstance(raw, dict):
            continue
        signal = str(raw.get("signal", "")).strip()
        severity = str(raw.get("severity", "")).strip().lower()
        evidence = str(raw.get("evidence", "")).strip()
        score = _coerce_score(raw.get("score"), default=45.0)
        if not signal or severity not in SEVERITY_RANK or not evidence:
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
            "evidence": "Timeline pressure requires explicit follow-up checkpoints.",
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
        normalized.append({"source_type": source_type, "source_id": source_id, "detail": detail})
    normalized.sort(
        key=lambda item: (
            order.get(str(item["source_type"]), 99),
            str(item["source_id"]),
            str(item["detail"]),
        )
    )
    if normalized:
        return normalized
    return [{"source_type": "offer_input", "source_id": "candidate", "detail": "Offer context baseline evidence."}]


def _derive_cadence_offsets(risk_signals: list[dict[str, Any]]) -> list[int]:
    deadline_severity = "low"
    for item in risk_signals:
        if str(item.get("signal")) == "deadline_pressure":
            deadline_severity = str(item.get("severity", "low")).lower()
            break

    if deadline_severity in {"critical", "high"}:
        return [0, 1, 3]
    if deadline_severity == "medium":
        return [0, 2, 4]
    return [0, 2, 5]


def _cadence_channels_for_risk(risk_signals: list[dict[str, Any]]) -> list[str]:
    lead_risk = str(risk_signals[0].get("signal", "deadline_pressure"))
    if lead_risk == "deadline_pressure":
        return ["email", "email", "phone"]
    if lead_risk == "compensation_compression":
        return ["email", "linkedin", "phone"]
    return ["email", "email", "linkedin"]


def _cadence_templates(
    *,
    role_label: str,
    target_salary: int,
    lead_leverage: str,
    lead_risk: str,
    evidence: str,
) -> list[dict[str, str]]:
    return [
        {
            "objective": "Reinforce value and confirm alignment",
            "message": (
                f"Thank recruiter for the {role_label} conversation and recap {lead_leverage} outcomes "
                f"supporting the compensation target of {target_salary}."
            ),
        },
        {
            "objective": "Provide concise evidence packet",
            "message": (
                f"Share one-paragraph proof tied to {lead_leverage}, including evidence: {evidence}"
            ),
        },
        {
            "objective": "Lock decision timeline and next checkpoint",
            "message": (
                f"Ask for explicit timeline updates and clarify how {lead_risk} concerns will be resolved."
            ),
        },
    ]


def _outcome_branch_sequences(*, max_cadence_day: int, risks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lead_risk = _signal_label(risks[0].get("signal", "deadline_pressure"))
    return [
        {
            "outcome": "positive_signal",
            "actions": [
                {"day_offset": 0, "action": "Confirm verbal alignment and request written offer summary."},
                {"day_offset": 1, "action": "Validate compensation components and acceptance deadline details."},
            ],
        },
        {
            "outcome": "needs_approval",
            "actions": [
                {"day_offset": 1, "action": "Provide compact evidence addendum for approver review."},
                {"day_offset": min(7, max_cadence_day + 1), "action": "Schedule decision checkpoint with recruiter."},
            ],
        },
        {
            "outcome": "stalled_or_pushback",
            "actions": [
                {"day_offset": 2, "action": f"Respond to {lead_risk} objections with bounded concession options."},
                {
                    "day_offset": min(10, max_cadence_day + 3),
                    "action": "Escalate to fallback trade package (scope, review timeline, or non-base upside).",
                },
            ],
        },
    ]


def _signal_label(signal: Any) -> str:
    return str(signal).strip().replace("_", " ") or "negotiation context"


def _first_sentence(text: str) -> str:
    normalized = str(text).strip()
    if not normalized:
        return ""
    if "." not in normalized:
        return normalized
    return normalized.split(".", 1)[0].strip() + "."


def _coerce_nonnegative_int(raw_value: Any, *, default: int) -> int:
    if not isinstance(raw_value, int) or isinstance(raw_value, bool) or raw_value < 0:
        return int(default)
    return int(raw_value)


def _coerce_score(raw_value: Any, *, default: float) -> float:
    if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
        return round(float(default), 2)
    score = float(raw_value)
    if 0.0 <= score <= 1.0:
        score *= 100.0
    return round(max(0.0, min(100.0, score)), 2)
