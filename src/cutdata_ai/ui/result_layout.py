"""Tool-family display structure shared by empty and populated results."""

from dataclasses import dataclass

from ..models.domain import MachiningResult
from ..models.schema import StructuredResponseError, validate_drilling_peck


@dataclass(frozen=True)
class ResultLayout:
    primary: tuple[str, ...]
    secondary: tuple[str, ...]
    derived: tuple[str, ...]


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


def result_layout_for_family(family: str) -> ResultLayout:
    return _FAMILY_LAYOUTS[family]


def peck_display(result: MachiningResult) -> tuple[str, str | None]:
    """Display the stored decision without inferring either pecking or Q.

    Older history can contain incomplete decisions. Keep it readable while
    explaining the missing information; live validation rejects invalid Q.
    """

    try:
        validate_drilling_peck(result)
    except StructuredResponseError:
        return "NOT SPECIFIED", "The saved peck decision is incomplete: no valid Q was supplied. Recalculate or verify the drilling cycle."
    if result.peck_recommended is False:
        return "NO PECK", None
    if result.peck_recommended is True:
        return f"Q{float(result.peck_mm):g} mm", None
    return "NOT SPECIFIED", "AI did not specify whether pecking is required; verify the drilling cycle."
