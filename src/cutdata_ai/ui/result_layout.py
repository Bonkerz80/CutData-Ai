"""Tool-family display structure shared by empty and populated results."""

from dataclasses import dataclass
from ..config.operations import (ROUGHING_WATERLINE, FACE_MILLING, FINISHING_WATERLINE,
                                 FINISHING_PLANE, FLAT_LAND_FINISHING)

from ..models.domain import MachiningResult
from ..models.schema import StructuredResponseError, validate_drilling_peck


@dataclass(frozen=True)
class ResultLayout:
    primary: tuple[str, ...]
    secondary: tuple[str, ...]
    derived: tuple[str, ...]
    axial_title: str = "DOC"
    lateral_title: str = "WOC / STEPOVER"
    lateral_fields: tuple[str, ...] = ("stepover_mm", "radial_doc_mm")


_MILLING_LAYOUT = ResultLayout(
    primary=("rpm", "feed_mm_min", "axial_doc_mm", "stepover_mm"),
    secondary=("cutting_speed", "feed_per_tooth", "coolant", "confidence"),
    derived=("radial_engagement", "axial_doc_ratio", "mrr", "rpm_usage", "feed_usage"),
)
_FAMILY_LAYOUTS = {
    "drill": ResultLayout(
        primary=("rpm", "feed_mm_min", "peck_mm"),
        secondary=("cutting_speed", "feed_per_rev", "cycle", "coolant", "confidence"),
        derived=("hole_ld_ratio", "rpm_usage", "feed_usage"),
    ),
    "reamer": ResultLayout(
        primary=("rpm", "feed_mm_min", "pre_ream_size_mm"),
        secondary=("cutting_speed", "feed_per_rev", "pre_ream_range", "cycle", "coolant", "confidence"),
        derived=("hole_ld_ratio", "rpm_usage", "feed_usage"),
    ),
    "tap": ResultLayout(
        primary=("rpm", "feed_mm_min", "tap_drill_mm"),
        secondary=("cutting_speed", "feed_per_rev", "cycle", "coolant", "confidence"),
        derived=("rpm_usage", "feed_usage", "tap_relationship"),
    ),
    "end_mill": _MILLING_LAYOUT,
    "indexable": _MILLING_LAYOUT,
}


_OPERATION_LAYOUTS = {
    ROUGHING_WATERLINE.casefold(): ResultLayout(
        _MILLING_LAYOUT.primary, _MILLING_LAYOUT.secondary, _MILLING_LAYOUT.derived,
        "DEPTH STEP", "RADIAL ENGAGEMENT", ("radial_doc_mm", "stepover_mm")),
    FACE_MILLING.casefold(): ResultLayout(
        _MILLING_LAYOUT.primary, _MILLING_LAYOUT.secondary, _MILLING_LAYOUT.derived,
        "DEPTH OF CUT", "WIDTH OF CUT", ("radial_doc_mm", "stepover_mm")),
    FINISHING_WATERLINE.casefold(): ResultLayout(
        ("rpm", "feed_mm_min", "axial_doc_mm"), _MILLING_LAYOUT.secondary,
        ("axial_doc_ratio", "rpm_usage", "feed_usage"), "Z STEP", "", ()),
    FINISHING_PLANE.casefold(): ResultLayout(
        ("rpm", "feed_mm_min", "stepover_mm"), _MILLING_LAYOUT.secondary,
        ("radial_engagement", "rpm_usage", "feed_usage"), "", "STEPOVER"),
    FLAT_LAND_FINISHING.casefold(): ResultLayout(
        ("rpm", "feed_mm_min", "stepover_mm"), _MILLING_LAYOUT.secondary,
        ("radial_engagement", "rpm_usage", "feed_usage"), "", "STEPOVER"),
}


def result_layout_for_family(family: str, operation: str = "") -> ResultLayout:
    if family in {"end_mill", "indexable"}:
        return _OPERATION_LAYOUTS.get(operation.casefold(), _MILLING_LAYOUT)
    return _FAMILY_LAYOUTS[family]


def effective_lateral_value(result: MachiningResult, layout: ResultLayout) -> float | None:
    """Use the operation's preferred lateral field; fallback only if absent."""
    for field in layout.lateral_fields:
        value = getattr(result, field)
        if value is not None:
            return value
    return None


def peck_display(result: MachiningResult) -> tuple[str, str | None]:
    """Display the stored decision without inferring either pecking or Q.

    Older history can contain incomplete decisions. Keep it readable while
    explaining the missing information; live validation rejects invalid Q.
    """

    if result.peck_recommended is False and result.peck_mm is not None:
        return "PECK DATA CONFLICT", "Stored result says no peck but also contains a Q value. Recalculate or verify before use."
    try:
        validate_drilling_peck(result)
    except StructuredResponseError:
        return "NOT SPECIFIED", "The saved peck decision is incomplete: no valid Q was supplied. Recalculate or verify the drilling cycle."
    if result.peck_recommended is False:
        return "NO PECK", None
    if result.peck_recommended is True:
        return f"Q{float(result.peck_mm):g} mm", None
    return "NOT SPECIFIED", "AI did not specify whether pecking is required; verify the drilling cycle."
