"""Compact, family-aware labels for exact recent-calculation records."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from ..config.constants import tool_family


_ACRONYMS = {
    "hss": "HSS",
    "hss-co": "HSS-Co",
    "co": "Co",
    "d2": "D2",
    "p20": "P20",
    "h13": "H13",
    "en1a": "EN1A",
    "en3": "EN3",
    "en8": "EN8",
    "en16": "EN16",
    "en19": "EN19",
    "en24": "EN24",
    "en32": "EN32",
    "xdpt": "XDPT",
    "apkt": "APKT",
    "mql": "MQL",
    "wp25pm": "WP25PM",
}


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _phrase(value: Any) -> str:
    """Title-case controlled labels while retaining workshop acronyms."""

    value = _text(value)
    if not value:
        return ""
    parts = re.split(r"(\s+|/|-)", value)
    formatted: list[str] = []
    for part in parts:
        if not part or part.isspace() or part in {"/", "-"}:
            formatted.append(part)
            continue
        formatted.append(_ACRONYMS.get(part.casefold(), part[:1].upper() + part[1:].lower()))
    return "".join(formatted)


def _identifier(value: Any) -> str:
    """Restore conventional uppercase for thread and insert identifiers."""

    value = _text(value)
    if not value:
        return ""
    if re.fullmatch(r"m\d+(?:\.\d+)?", value, flags=re.IGNORECASE):
        return value.upper()
    return _ACRONYMS.get(value.casefold(), value.upper())


def _number(parameters: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        value = parameters.get(name)
        if value is None or value == "":
            continue
        try:
            result = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(result) and result > 0:
            return result
    return None


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    if abs(value - round(value)) < 1e-8:
        return f"{value:,.0f}"
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def _material(request: Mapping[str, Any]) -> str:
    material = _phrase(request.get("material"))
    if material and material.casefold() != "custom / other":
        return material
    return _phrase(request.get("custom_material")) or material


def _tool_material(parameters: Mapping[str, Any]) -> str:
    return _phrase(parameters.get("tool_material") or parameters.get("tool_grade"))


def _coolant(parameters: Mapping[str, Any]) -> str:
    value = _text(parameters.get("coolant_type"))
    if value:
        lowered = value.casefold()
        if lowered in {"none / dry", "dry", "none"}:
            return "Dry"
        if lowered == "flood coolant":
            return "Flood"
        if lowered == "through-tool coolant":
            return "Through-tool"
        return _phrase(value)
    if parameters.get("internal_coolant") is True:
        return "Through-tool"
    if parameters.get("flood_coolant") is True:
        return "Flood"
    return ""


def _operation(parameters: Mapping[str, Any], request: Mapping[str, Any]) -> str:
    return _phrase(parameters.get("operation") or request.get("operation"))


def _flute_text(parameters: Mapping[str, Any]) -> str:
    count = _number(parameters, "flute_count", "insert_count")
    if count is None:
        return ""
    return f"{_fmt(count)}F" if "flute_count" in parameters else f"{_fmt(count)} inserts"


def _tool_title(request: Mapping[str, Any], parameters: Mapping[str, Any], family: str) -> str:
    raw_type = _text(request.get("tool_type"))
    lowered = raw_type.casefold()
    material = _material(request)
    tool_material = _tool_material(parameters)
    diameter = _number(parameters, "diameter_mm", "cutter_diameter_mm")
    diameter_text = f"Ø{_fmt(diameter)}" if diameter is not None else ""
    flutes = _flute_text(parameters)

    if family == "drill":
        kind = "Drill"
        if "spot" in lowered:
            kind = "Spot Drill"
        elif "counter" in lowered:
            kind = "Countersink"
        elif "chamfer" in lowered:
            kind = "Chamfer Mill"
        pieces = [item for item in (diameter_text, tool_material, kind) if item]
    elif family == "reamer":
        pieces = [item for item in (diameter_text, tool_material, "Reamer") if item]
    elif family == "tap":
        thread_size = _identifier(parameters.get("thread_size"))
        pitch = _number(parameters, "pitch_mm")
        thread = thread_size or diameter_text
        if thread and pitch is not None:
            thread = f"{thread} × {_fmt(pitch)}"
        tap_type = _phrase(parameters.get("tap_type")) or "Tap"
        pieces = [item for item in (thread, tap_type) if item]
    elif family == "indexable":
        cutter_type = _phrase(parameters.get("cutter_type"))
        if not cutter_type:
            cutter_type = "Face Mill" if "face mill" in lowered else "Indexable End Mill"
        pieces = [item for item in (diameter_text, cutter_type) if item]
    else:
        if "ball nose" in lowered:
            kind = "Ball Nose"
        elif "bull nose" in lowered:
            radius = _number(parameters, "corner_radius_mm")
            kind = f"Bull Nose R{_fmt(radius)}" if radius is not None else "Bull Nose"
        elif "thread mill" in lowered:
            kind = "Thread Mill"
        else:
            kind = "End Mill"
        size = diameter_text
        if "thread mill" in lowered:
            size = _identifier(parameters.get("thread_size")) or size
        pieces = [item for item in (size, tool_material, flutes, kind) if item]

    if family == "indexable" and flutes:
        pieces.extend(("·", flutes))
    if material:
        pieces.extend(("·", material))
    return " ".join(pieces) or _phrase(raw_type) or "Machining calculation"


def _detail(request: Mapping[str, Any], parameters: Mapping[str, Any], family: str) -> str:
    details: list[str] = []
    operation = _operation(parameters, request)
    coolant = _coolant(parameters)

    if family == "drill":
        depth = _number(parameters, "hole_depth_mm")
        pilot = _number(parameters, "existing_pilot_hole_diameter_mm")
        if depth is not None:
            details.append(f"{_fmt(depth)} mm deep")
        if pilot is not None:
            details.append(f"Ø{_fmt(pilot)} pilot")
        if coolant:
            details.append(coolant)
    elif family == "reamer":
        start = _number(parameters, "existing_hole_diameter_mm")
        depth = _number(parameters, "hole_depth_mm")
        if start is not None:
            details.append(f"Start Ø{_fmt(start)}")
        if depth is not None:
            details.append(f"{_fmt(depth)} mm deep")
        if coolant:
            details.append(coolant)
    elif family == "tap":
        material = _tool_material(parameters)
        depth = _number(parameters, "thread_depth_mm")
        if material:
            details.append(material)
        if depth is not None:
            details.append(f"{_fmt(depth)} mm deep")
        if coolant:
            details.append(coolant)
    elif family == "indexable":
        if operation:
            details.append(operation)
        axial = _number(parameters, "axial_doc_mm")
        radial = _number(parameters, "radial_doc_mm")
        if axial is not None:
            details.append(f"{_fmt(axial)} mm DOC")
        if radial is not None:
            details.append(f"{_fmt(radial)} mm WOC")
        code = _identifier(parameters.get("insert_code"))
        grade = _identifier(parameters.get("insert_grade"))
        if code and grade:
            details.append(f"{code} / {grade}")
        elif code or grade:
            details.append(code or grade)
    else:
        if operation:
            details.append(operation)
        axial = _number(parameters, "axial_doc_mm")
        radial = _number(parameters, "radial_doc_mm")
        stock = _number(parameters, "stock_remaining_mm")
        if axial is not None:
            details.append(f"{_fmt(axial)} mm DOC")
        if radial is not None:
            details.append(f"{_fmt(radial)} mm WOC")
        if stock is not None:
            details.append(f"{_fmt(stock)} mm stock")

    return " · ".join(details)


def build_recent_summary(normalized_request: Mapping[str, Any]) -> tuple[str, str]:
    """Return the two compact lines shown for one exact history record."""

    request = normalized_request if isinstance(normalized_request, Mapping) else {}
    parameters = request.get("parameters", {})
    if not isinstance(parameters, Mapping):
        parameters = {}
    family = tool_family(str(request.get("tool_type", "")))
    return _tool_title(request, parameters, family), _detail(request, parameters, family)


def recent_item_text(normalized_request: Mapping[str, Any]) -> str:
    """Return a QListWidget-friendly one- or two-line history label."""

    title, detail = build_recent_summary(normalized_request)
    return f"{title}\n{detail}" if detail else title
