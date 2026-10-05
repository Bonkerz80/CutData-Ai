"""OpenAI Structured Outputs schema and conversion helpers."""

from __future__ import annotations

import json
import math
from typing import Any

from .domain import MachiningResult


# Strict structured outputs require every property to be listed as required.
# Nullable fields let the model leave values that do not apply empty instead of
# inventing irrelevant machining data.
MACHINING_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "rpm": {"type": ["number", "null"], "description": "AI-selected starting spindle speed; local code may lower it for hard machine limits."},
        "cutting_speed_m_min": {"type": ["number", "null"], "description": "AI recommendation, checked locally from diameter and final RPM."},
        "feed_mm_min": {"type": ["number", "null"], "description": "AI-selected starting feed, checked locally against its deterministic relationship."},
        "feed_per_tooth_mm": {"type": ["number", "null"], "description": "AI-selected milling feed per tooth; may be derived only when feed arithmetic requires it."},
        "feed_per_rev_mm": {"type": ["number", "null"], "description": "AI-selected feed per revolution; rigid tapping must use the exact requested pitch."},
        "peck_mm": {"type": ["number", "null"], "description": "AI-selected peck depth; never invent a value from hole depth locally."},
        "peck_recommended": {"type": ["boolean", "null"], "description": "AI decision on whether the operation should peck."},
        "recommended_cycle": {"type": ["string", "null"], "description": "AI-selected machine cycle, when applicable."},
        "axial_doc_mm": {"type": ["number", "null"], "description": "AI-selected axial depth of cut."},
        "radial_doc_mm": {"type": ["number", "null"], "description": "AI-selected radial engagement or width."},
        "stepover_mm": {"type": ["number", "null"], "description": "AI-selected stepover, when applicable."},
        "plunge_feed_mm_min": {"type": ["number", "null"], "description": "AI-selected plunge feed, when applicable."},
        "ramp_feed_mm_min": {"type": ["number", "null"], "description": "AI-selected ramp feed, when applicable."},
        "pre_ream_size_mm": {"type": ["number", "null"], "description": "AI-selected pre-ream size; do not calculate a fallback locally."},
        "pre_ream_range_mm": {"type": ["string", "null"], "description": "AI-selected pre-ream range, when applicable."},
        "reaming_stock_mm": {"type": ["number", "null"], "description": "AI-selected reaming stock; do not calculate a fallback locally."},
        "tap_pitch_mm": {"type": ["number", "null"], "description": "The requested thread pitch represented in the structured result."},
        "tap_drill_mm": {"type": ["number", "null"], "description": "AI-selected tapping drill size; do not derive it from nominal diameter minus pitch."},
        "estimated_spindle_power_kw": {"type": ["number", "null"], "description": "Optional AI estimate of spindle power in kW; never used to create a recommendation locally."},
        "estimated_spindle_torque_nm": {"type": ["number", "null"], "description": "Optional AI estimate of spindle torque in N·m; never used to create a recommendation locally."},
        "engagement_description": {"type": ["string", "null"], "description": "Optional concise AI description of the cutter engagement."},
        "setup_risk": {
            "type": ["string", "null"],
            "enum": ["low", "medium", "high", None],
            "description": "Optional AI setup-risk assessment: low, medium, or high.",
        },
        "recommendation_summary": {"type": ["string", "null"], "description": "Optional concise AI summary of the recommendation."},
        "recommended_operation": {"type": ["string", "null"], "description": "Recommended ENCY-style operation selected by the AI, especially for AI-guided jobs."},
        "recommended_strategy": {"type": ["string", "null"], "description": "Short practical machining strategy."},
        "recommended_entry_method": {"type": ["string", "null"], "description": "Recommended approach, plunge or ramp method where relevant."},
        "recommended_finish_allowance_mm": {"type": ["number", "null"], "description": "AI-selected finish allowance in mm."},
        "recommended_pass_count": {"type": ["integer", "null"], "description": "AI-selected number of passes, when meaningful."},
        "pass_plan": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "stage": {"type": "string"},
                    "passes": {"type": ["integer", "null"]},
                    "operation": {"type": ["string", "null"]},
                    "axial_doc_mm": {"type": ["number", "null"]},
                    "radial_engagement_mm": {"type": ["number", "null"]},
                    "stepover_mm": {"type": ["number", "null"]},
                    "stock_to_leave_mm": {"type": ["number", "null"]},
                    "rpm": {"type": ["number", "null"]},
                    "feed_mm_min": {"type": ["number", "null"]},
                    "notes": {"type": "string"},
                },
                "required": ["stage", "passes", "operation", "axial_doc_mm", "radial_engagement_mm", "stepover_mm", "stock_to_leave_mm", "rpm", "feed_mm_min", "notes"],
            },
        },
        "coolant": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "notes": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "rpm",
        "cutting_speed_m_min",
        "feed_mm_min",
        "feed_per_tooth_mm",
        "feed_per_rev_mm",
        "peck_mm",
        "peck_recommended",
        "recommended_cycle",
        "axial_doc_mm",
        "radial_doc_mm",
        "stepover_mm",
        "plunge_feed_mm_min",
        "ramp_feed_mm_min",
        "pre_ream_size_mm",
        "pre_ream_range_mm",
        "reaming_stock_mm",
        "tap_pitch_mm",
        "tap_drill_mm",
        "estimated_spindle_power_kw",
        "estimated_spindle_torque_nm",
        "engagement_description",
        "setup_risk",
        "recommendation_summary",
        "recommended_operation",
        "recommended_strategy",
        "recommended_entry_method",
        "recommended_finish_allowance_mm",
        "recommended_pass_count",
        "pass_plan",
        "coolant",
        "confidence",
        "notes",
        "warnings",
    ],
}


class StructuredResponseError(ValueError):
    """Raised when the model response cannot be used as machining data."""


def _number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise StructuredResponseError(f"Structured response field '{field_name}' is not numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise StructuredResponseError(f"Structured response field '{field_name}' is not numeric") from exc
    if not math.isfinite(number):
        raise StructuredResponseError(f"Structured response field '{field_name}' is not finite")
    return number


def validate_drilling_peck(result: MachiningResult) -> None:
    """Reject incomplete or contradictory decisions without choosing Q locally."""

    decision = result.peck_recommended
    if decision is not None and not isinstance(decision, bool):
        raise StructuredResponseError("Peck recommendation must be boolean or null")
    if decision is False and result.peck_mm is not None:
        raise StructuredResponseError("Peck recommendation is false but a Q value was supplied; peck_mm must be null")
    if decision is True:
        peck = _number(result.peck_mm, "peck_mm")
        if peck is None or peck <= 0:
            raise StructuredResponseError("Pecking was recommended but no positive peck depth was provided")


def result_from_dict(payload: dict[str, Any]) -> MachiningResult:
    """Convert a strict-schema object and reject missing/invalid core data."""

    if not isinstance(payload, dict):
        raise StructuredResponseError("Structured response was not an object")
    if "rpm" not in payload or "feed_mm_min" not in payload:
        raise StructuredResponseError("Structured response is missing required machining values")

    notes = payload.get("notes", [])
    warnings = payload.get("warnings", [])
    if not isinstance(notes, list) or not all(isinstance(item, str) for item in notes):
        raise StructuredResponseError("Structured response notes must be a list of strings")
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise StructuredResponseError("Structured response warnings must be a list of strings")

    rpm = _number(payload.get("rpm"), "rpm")
    feed = _number(payload.get("feed_mm_min"), "feed_mm_min")
    if rpm is None or rpm <= 0:
        raise StructuredResponseError("Structured response must contain a positive RPM")
    if feed is None or feed < 0:
        raise StructuredResponseError("Structured response must contain a non-negative feed")

    confidence = payload.get("confidence", "medium")
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"

    numeric_fields = (
        "cutting_speed_m_min",
        "feed_per_tooth_mm",
        "feed_per_rev_mm",
        "peck_mm",
        "axial_doc_mm",
        "radial_doc_mm",
        "stepover_mm",
        "plunge_feed_mm_min",
        "ramp_feed_mm_min",
        "pre_ream_size_mm",
        "reaming_stock_mm",
        "tap_pitch_mm",
        "tap_drill_mm",
        "estimated_spindle_power_kw",
        "estimated_spindle_torque_nm",
        "recommended_finish_allowance_mm",
    )
    converted = {name: _number(payload.get(name), name) for name in numeric_fields}
    for name, value in converted.items():
        if value is not None and value < 0:
            raise StructuredResponseError(f"Structured response field '{name}' cannot be negative")

    peck_recommended = payload.get("peck_recommended")
    if peck_recommended is not None and not isinstance(peck_recommended, bool):
        raise StructuredResponseError("Structured response field 'peck_recommended' must be boolean or null")
    recommended_cycle = payload.get("recommended_cycle")
    if recommended_cycle is not None and not isinstance(recommended_cycle, str):
        raise StructuredResponseError("Structured response field 'recommended_cycle' must be string or null")
    pre_ream_range = payload.get("pre_ream_range_mm")
    if pre_ream_range is not None and not isinstance(pre_ream_range, str):
        raise StructuredResponseError("Structured response field 'pre_ream_range_mm' must be string or null")
    optional_text: dict[str, str | None] = {}
    for field_name in ("engagement_description", "recommendation_summary"):
        value = payload.get(field_name)
        if value is not None and not isinstance(value, str):
            raise StructuredResponseError(f"Structured response field '{field_name}' must be string or null")
        optional_text[field_name] = value
    setup_risk = payload.get("setup_risk")
    if setup_risk is not None and setup_risk not in {"low", "medium", "high"}:
        setup_risk = None
    coolant = payload.get("coolant", "")
    if not isinstance(coolant, str):
        raise StructuredResponseError("Structured response field 'coolant' must be a string")

    research_sources = payload.get("research_sources", [])
    if not isinstance(research_sources, list):
        research_sources = []
    clean_sources: list[dict[str, str]] = []
    for source in research_sources:
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            continue
        title = source.get("title", "")
        clean_sources.append({"title": title if isinstance(title, str) else "", "url": url})

    def string_list(field_name: str) -> list[str]:
        value = payload.get(field_name, [])
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]

    research_status = payload.get("research_status", "not_run")
    if research_status not in {"not_run", "not_applicable", "searched", "no_sources", "not_used", "unavailable"}:
        research_status = "not_run"
    verification_status = payload.get("verification_status", "not_run")
    if verification_status not in {"not_run", "cross_checked", "review_required", "check_incomplete"}:
        verification_status = "not_run"
    verification_summary = payload.get("verification_summary", "")
    if not isinstance(verification_summary, str):
        verification_summary = ""
    verification_response_id = payload.get("verification_response_id", "")
    if not isinstance(verification_response_id, str):
        verification_response_id = ""

    string_fields = ("recommended_operation", "recommended_strategy", "recommended_entry_method")
    optional_text: dict[str, str | None] = dict(optional_text)
    for field_name in string_fields:
        value = payload.get(field_name)
        if value is not None and not isinstance(value, str):
            raise StructuredResponseError(f"Structured response field '{field_name}' must be string or null")
        optional_text[field_name] = value
    pass_count = payload.get("recommended_pass_count")
    if pass_count is not None and (isinstance(pass_count, bool) or not isinstance(pass_count, int) or pass_count < 1):
        raise StructuredResponseError("Structured response field 'recommended_pass_count' must be a positive integer or null")
    pass_plan = payload.get("pass_plan", [])
    if not isinstance(pass_plan, list):
        raise StructuredResponseError("Structured response field 'pass_plan' must be a list")
    clean_plan: list[dict[str, Any]] = []
    for index, stage in enumerate(pass_plan):
        if not isinstance(stage, dict) or not isinstance(stage.get("stage"), str):
            raise StructuredResponseError(f"Pass plan stage {index + 1} must be an object with a stage name")
        clean = dict(stage)
        stage_passes = clean.get("passes")
        if stage_passes is not None and (isinstance(stage_passes, bool) or not isinstance(stage_passes, int) or stage_passes < 1):
            raise StructuredResponseError(f"Pass plan stage {index + 1} 'passes' must be a positive integer or null")
        clean["passes"] = stage_passes
        for field_name in ("operation", "notes"):
            if clean.get(field_name) is not None and not isinstance(clean[field_name], str):
                raise StructuredResponseError(f"Pass plan stage {index + 1} '{field_name}' must be text")
        for field_name in ("axial_doc_mm", "radial_engagement_mm", "stepover_mm", "stock_to_leave_mm", "rpm", "feed_mm_min"):
            if field_name not in clean:
                clean[field_name] = None if field_name != "notes" else ""
            number = _number(clean[field_name], f"pass_plan[{index}].{field_name}")
            if number is not None and number < 0:
                raise StructuredResponseError(f"Pass plan stage {index + 1} '{field_name}' cannot be negative")
            clean[field_name] = number
        clean.setdefault("operation", None)
        clean.setdefault("notes", "")
        clean_plan.append(clean)

    result = MachiningResult(
        rpm=rpm,
        feed_mm_min=feed,
        **converted,
        peck_recommended=peck_recommended,
        recommended_cycle=recommended_cycle,
        pre_ream_range_mm=pre_ream_range,
        engagement_description=optional_text["engagement_description"],
        setup_risk=setup_risk,
        recommendation_summary=optional_text["recommendation_summary"],
        recommended_operation=optional_text["recommended_operation"],
        recommended_strategy=optional_text["recommended_strategy"],
        recommended_entry_method=optional_text["recommended_entry_method"],
        recommended_pass_count=pass_count,
        pass_plan=clean_plan,
        coolant=coolant,
        confidence=confidence,
        notes=notes,
        warnings=warnings,
        research_status=research_status,
        research_sources=clean_sources,
        verification_status=verification_status,
        verification_summary=verification_summary,
        verification_findings=string_list("verification_findings"),
        history_comparison=string_list("history_comparison"),
        verification_response_id=verification_response_id,
    )
    return result


def result_from_json(value: str) -> MachiningResult:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise StructuredResponseError("Stored structured response was not valid JSON") from exc
    return result_from_dict(payload)
