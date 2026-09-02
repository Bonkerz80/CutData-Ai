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
        "rpm": {"type": ["number", "null"]},
        "cutting_speed_m_min": {"type": ["number", "null"]},
        "feed_mm_min": {"type": ["number", "null"]},
        "feed_per_tooth_mm": {"type": ["number", "null"]},
        "feed_per_rev_mm": {"type": ["number", "null"]},
        "peck_mm": {"type": ["number", "null"]},
        "peck_recommended": {"type": ["boolean", "null"]},
        "recommended_cycle": {"type": ["string", "null"]},
        "axial_doc_mm": {"type": ["number", "null"]},
        "radial_doc_mm": {"type": ["number", "null"]},
        "stepover_mm": {"type": ["number", "null"]},
        "plunge_feed_mm_min": {"type": ["number", "null"]},
        "ramp_feed_mm_min": {"type": ["number", "null"]},
        "pre_ream_size_mm": {"type": ["number", "null"]},
        "pre_ream_range_mm": {"type": ["string", "null"]},
        "reaming_stock_mm": {"type": ["number", "null"]},
        "tap_pitch_mm": {"type": ["number", "null"]},
        "tap_drill_mm": {"type": ["number", "null"]},
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
    )
    converted = {name: _number(payload.get(name), name) for name in numeric_fields}
    for name, value in converted.items():
        if value is not None and value < 0:
            raise StructuredResponseError(f"Structured response field '{name}' cannot be negative")

    result = MachiningResult(
        rpm=rpm,
        feed_mm_min=feed,
        **converted,
        peck_recommended=payload.get("peck_recommended"),
        recommended_cycle=payload.get("recommended_cycle"),
        pre_ream_range_mm=payload.get("pre_ream_range_mm"),
        coolant=str(payload.get("coolant", "")),
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
