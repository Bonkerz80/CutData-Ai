"""Select nearby prior guided calculations as cautious comparison context."""

from __future__ import annotations

import json
from typing import Any

from ..models.domain import MachiningRequest
from .normalization import normalize_request


_DEPTH_FIELDS = (
    "job_depth_mm",
    "material_thickness_mm",
    "hole_depth_mm",
    "thread_depth_mm",
    "pocket_depth_mm",
    "cut_depth_mm",
    "total_depth_mm",
)
_GEOMETRY_FIELDS = frozenset((*_DEPTH_FIELDS, "job_description"))
_RESULT_FIELDS = (
    "rpm",
    "cutting_speed_m_min",
    "feed_mm_min",
    "feed_per_tooth_mm",
    "feed_per_rev_mm",
    "axial_doc_mm",
    "radial_doc_mm",
    "stepover_mm",
    "recommended_pass_count",
    "recommended_operation",
    "recommended_strategy",
    "confidence",
)
_TOOL_FACT_FIELDS = (
    "manufacturer",
    "model",
    "tool_type",
    "diameter_mm",
    "effective_cutting_diameter_mm",
    "tool_material",
    "coating",
    "flute_count",
    "insert_count",
    "approach_angle_deg",
    "cutting_edge_length_mm",
    "overall_length_mm",
    "default_stickout_mm",
)
_INSERT_FACT_FIELDS = (
    "manufacturer",
    "model",
    "designation",
    "grade",
    "material",
    "coating",
    "chipbreaker",
    "geometry",
    "corner_radius_mm",
)


def _depth(parameters: dict[str, Any]) -> float | None:
    for key in _DEPTH_FIELDS:
        value = parameters.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _tool_signature(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    tool = {key: snapshot.get(key) for key in _TOOL_FACT_FIELDS if snapshot.get(key) not in (None, "")}
    insert = snapshot.get("insert")
    if isinstance(insert, dict):
        insert_facts = {key: insert.get(key) for key in _INSERT_FACT_FIELDS if insert.get(key) not in (None, "")}
    else:
        insert_facts = {}
    return {"tool": tool, "insert": insert_facts}


def _has_material_hardness_conflict(request: dict[str, Any]) -> bool:
    hardness = request.get("hardness_hrc")
    if hardness in (None, 0):
        return False
    material = str(request.get("material", "")).strip().casefold()
    return not (
        material == "custom / other"
        or material == "toolox 44"
        or "hardened" in material
    )


def _is_comparable(current: dict[str, Any], previous: dict[str, Any]) -> bool:
    if previous.get("workflow_mode") != "guided":
        return False
    if _has_material_hardness_conflict(previous):
        return False

    for key in (
        "machine",
        "material",
        "custom_material",
        "hardness_hrc",
        "tool_type",
        "operation",
        "workflow_mode",
    ):
        if current.get(key) != previous.get(key):
            return False

    if _tool_signature(current.get("tool_snapshot")) != _tool_signature(previous.get("tool_snapshot")):
        return False

    current_parameters = current.get("parameters", {})
    previous_parameters = previous.get("parameters", {})
    if not isinstance(current_parameters, dict) or not isinstance(previous_parameters, dict):
        return False
    current_fixed = {key: value for key, value in current_parameters.items() if key not in _GEOMETRY_FIELDS}
    previous_fixed = {key: value for key, value in previous_parameters.items() if key not in _GEOMETRY_FIELDS}
    return current_fixed == previous_fixed


def related_calculation_history(
    database: Any,
    request: MachiningRequest,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return nearby, same-setup AI results without treating them as proven data."""

    if request.workflow_mode != "guided" and request.operation.strip().casefold() != "ai guided":
        return []
    current = normalize_request(request)
    current_parameters = current.get("parameters", {})
    current_depth = _depth(current_parameters)
    if current_depth is None:
        return []

    candidates: list[tuple[float, int, dict[str, Any]]] = []
    seen_depths: set[float] = set()
    for position, row in enumerate(database.recent(25)):
        if str(row.get("source", "")).casefold() not in {"ai", "cache"}:
            continue
        try:
            previous = json.loads(row.get("normalized_request_json", "{}"))
            result = json.loads(row.get("result_json", "{}"))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(previous, dict) or not isinstance(result, dict) or not _is_comparable(current, previous):
            continue
        previous_parameters = previous.get("parameters", {})
        previous_depth = _depth(previous_parameters if isinstance(previous_parameters, dict) else {})
        if previous_depth is None or abs(previous_depth - current_depth) < 1e-6:
            continue
        depth_key = round(previous_depth, 4)
        if depth_key in seen_depths:
            continue
        seen_depths.add(depth_key)

        selected_result = {key: result.get(key) for key in _RESULT_FIELDS if result.get(key) is not None}
        warnings = result.get("warnings", [])
        if isinstance(warnings, list) and warnings:
            selected_result["warnings"] = [str(item) for item in warnings[:3]]
        status = str(result.get("verification_status", "legacy_unverified"))
        if status == "review_required":
            trust_label = "Previously flagged for review; do not reuse without reassessment."
        elif status == "cross_checked":
            trust_label = "AI cross-checked, but not confirmed by an operator or cutting trial."
        else:
            trust_label = "Historical AI recommendation; not confirmed by an operator or cutting trial."

        entry = {
            "depth_mm": previous_depth,
            "depth_delta_from_current_mm": round(previous_depth - current_depth, 4),
            "created_at": str(row.get("created_at", "")),
            "model": str(row.get("model", "")),
            "source_status": trust_label,
            "verification_status": status,
            "result": selected_result,
        }
        sources = result.get("research_sources", [])
        if isinstance(sources, list) and sources:
            entry["research_sources"] = [source for source in sources[:5] if isinstance(source, dict)]
        candidates.append((abs(previous_depth - current_depth), position, entry))

    candidates.sort(key=lambda item: (item[0], item[1]))
    return [entry for _, _, entry in candidates[:max(0, limit)]]


def small_depth_change_findings(request: MachiningRequest, result: dict[str, Any]) -> list[str]:
    """Flag material changes to cutting settings across nearby depths for review."""

    current_parameters = request.parameters
    current_depth = _depth(current_parameters)
    if current_depth is None:
        return []

    history = request.comparison_history
    if not history:
        return []
    nearest = min(
        history,
        key=lambda item: abs(float(item.get("depth_delta_from_current_mm", float("inf")))),
    )
    try:
        prior_depth = float(nearest["depth_mm"])
        depth_delta = abs(float(nearest.get("depth_delta_from_current_mm", current_depth - prior_depth)))
    except (KeyError, TypeError, ValueError):
        return []
    if depth_delta > max(0.5, max(abs(current_depth), abs(prior_depth)) * 0.02):
        return []

    prior = nearest.get("result", {})
    if not isinstance(prior, dict):
        return []
    labels = {
        "rpm": "RPM",
        "cutting_speed_m_min": "cutting speed",
        "feed_per_tooth_mm": "feed per tooth",
        "axial_doc_mm": "axial DOC",
        "radial_doc_mm": "radial engagement",
        "stepover_mm": "stepover",
    }
    changes: list[str] = []
    for key, label in labels.items():
        old = prior.get(key)
        new = result.get(key)
        try:
            old_number = float(old)
            new_number = float(new)
        except (TypeError, ValueError):
            continue
        if old_number <= 0 or new_number <= 0:
            continue
        percent = abs(new_number - old_number) / abs(old_number) * 100.0
        if percent >= 15.0:
            changes.append(f"{label}: {old_number:g} → {new_number:g} ({percent:.0f}% change)")
    if not changes:
        return []
    return [
        f"Only total depth changed by {depth_delta:g} mm versus the {prior_depth:g} mm history entry, but "
        + "; ".join(changes)
        + ". The verifier must give a physical or evidence-based reason for these changes."
    ]
