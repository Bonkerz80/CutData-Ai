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
    """Reject an incomplete positive decision without choosing Q locally."""

    decision = result.peck_recommended
    if decision is not None and not isinstance(decision, bool):
        raise StructuredResponseError("Peck recommendation must be boolean or null")
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
        coolant=coolant,
        confidence=confidence,
        notes=notes,
        warnings=warnings,
    )
    return result


def result_from_json(value: str) -> MachiningResult:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise StructuredResponseError("Stored structured response was not valid JSON") from exc
    return result_from_dict(payload)
