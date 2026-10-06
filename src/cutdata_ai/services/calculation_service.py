"""Local validation, arithmetic correction, and cache-aware calculation flow."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from typing import Any, Callable

from ..config.constants import tool_family
from ..config.operations import active_parameters, legacy_operation_warning
from ..database.database import Database
from ..models.domain import CalculationOutcome, MachiningRequest, MachiningResult, MachineProfile
from ..models.schema import StructuredResponseError, result_from_dict, result_from_json, validate_drilling_peck
from ..prompts.machining import build_user_prompt
from .calculation_history import related_calculation_history, small_depth_change_findings
from .normalization import model_cache_identity, normalize_request, request_hash
from .openai_service import OpenAIServiceError, ServiceResponse


class CalculationInputError(ValueError):
    """Raised when the request cannot be safely sent for calculation."""


def cutting_speed_m_min(diameter_mm: float, rpm: float) -> float:
    if diameter_mm <= 0 or rpm < 0:
        raise ValueError("Diameter must be positive and RPM cannot be negative")
    return math.pi * diameter_mm * rpm / 1000.0


def milling_feed_mm_min(rpm: float, flute_count: int, feed_per_tooth_mm: float) -> float:
    if rpm < 0 or flute_count <= 0 or feed_per_tooth_mm < 0:
        raise ValueError("RPM, flute count, and feed per tooth must be valid")
    return rpm * flute_count * feed_per_tooth_mm


def drilling_feed_mm_min(rpm: float, feed_per_rev_mm: float) -> float:
    if rpm < 0 or feed_per_rev_mm < 0:
        raise ValueError("RPM and feed per revolution must be valid")
    return rpm * feed_per_rev_mm


def tapping_feed_mm_min(rpm: float, pitch_mm: float) -> float:
    if rpm < 0 or pitch_mm <= 0:
        raise ValueError("RPM and pitch must be valid")
    return rpm * pitch_mm


def _merge_research_sources(*collections: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    positions: dict[str, int] = {}
    for sources in collections:
        for source in sources:
            if not isinstance(source, dict):
                continue
            url = str(source.get("url", "")).strip()
            if not url.startswith(("https://", "http://")):
                continue
            key = url.casefold()
            title = str(source.get("title", "")).strip()
            if key in positions:
                existing = merged[positions[key]]
                if title and not existing.get("title"):
                    existing["title"] = title
                continue
            positions[key] = len(merged)
            merged.append({"title": title, "url": url})
            if len(merged) >= 12:
                return merged
    return merged


def _combine_usage(primary: dict[str, Any], reviewer: dict[str, Any]) -> dict[str, Any]:
    combined = dict(primary)
    if not reviewer:
        return combined
    combined["primary_call"] = dict(primary)
    combined["independent_check"] = dict(reviewer)
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        values = [value.get(key) for value in (primary, reviewer)]
        numeric = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
        if numeric:
            combined[key] = sum(numeric)
    return combined


def _number(parameters: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = parameters.get(name)
        if value is not None and value != "":
            try:
                number = float(value)
                return number if math.isfinite(number) else None
            except (TypeError, ValueError):
                return None
    return None


def validate_request(request: MachiningRequest, machine: MachineProfile) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) without modifying user inputs."""

    errors: list[str] = []
    warnings: list[str] = []
    guided = request.workflow_mode == "guided" or request.operation.strip().casefold() == "ai guided"
    legacy_warning = "" if guided else legacy_operation_warning(request.tool_type, request.operation)
    if legacy_warning:
        errors.append(legacy_warning)
    p = request.parameters
    family = tool_family(request.tool_type)
    diameter = _number(p, "diameter_mm", "cutter_diameter_mm")
    if diameter is None or diameter <= 0:
        errors.append("Enter a diameter greater than 0 mm.")
    if request.material.casefold() == "custom / other" and not request.custom_material.strip():
        errors.append("Describe the custom material before calculating.")

    for field_name, label in (
        ("hole_depth_mm", "Hole depth"),
        ("material_thickness_mm", "Material thickness"),
        ("thread_depth_mm", "Thread depth"),
        ("axial_doc_mm", "Axial DOC"),
        ("radial_doc_mm", "Radial engagement"),
        ("stock_remaining_mm", "Stock remaining"),
        ("pocket_depth_mm", "Pocket depth"),
    ):
        value = _number(p, field_name)
        if value is not None and value < 0:
            errors.append(f"{label} cannot be negative.")

    count = _number(p, "flute_count", "insert_count")
    if family in {"end_mill", "indexable"} and (count is None or count < 1 or count > 100) and not guided:
        errors.append("Enter a sensible flute or insert count (at least 1).")
    elif family in {"end_mill", "indexable"} and (count is None or count < 1) and guided:
        warnings.append("Tool flute/insert count is unknown; verify the feed relationship before running.")

    if family == "tap":
        pitch = _number(p, "pitch_mm")
        if pitch is None or pitch <= 0:
            errors.append("Enter a pitch greater than 0 mm.")

    if request.hardness_hrc is not None and request.hardness_hrc < 0:
        errors.append("Hardness cannot be negative.")
    if request.hardness_hrc is not None and request.hardness_hrc > 70:
        warnings.append("Hardness is above the usual HRC range; confirm the material specification.")

    if family == "drill" and diameter:
        pilot = _number(p, "existing_pilot_hole_diameter_mm")
        if pilot is not None and pilot >= diameter:
            errors.append("Pilot hole must be smaller than the drill diameter.")

    if family == "reamer" and diameter:
        existing = _number(p, "existing_hole_diameter_mm")
        if existing is not None and existing > 0:
            stock = diameter - existing
            if stock <= 0:
                errors.append("Existing hole must be smaller than the reamer diameter.")

    if machine.max_rpm <= 0:
        errors.append("The selected machine profile has no valid maximum spindle speed.")
    if machine.max_feed_mm_min <= 0:
        errors.append("The selected machine profile has no valid maximum feed.")
    return errors, warnings


def _close(a: float | None, b: float | None, relative: float = 0.02) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(0.02, abs(b) * relative)


def _enabled(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def validate_and_correct_result(
    result: MachiningResult,
    request: MachiningRequest,
    machine: MachineProfile,
) -> tuple[MachiningResult, list[str]]:
    """Validate arithmetic and hard machine limits without inventing advice.

    The AI owns machining choices such as pecking, tap-drill size, and reaming
    allowances. This function only derives dependent arithmetic values and
    reduces RPM when a hard machine limit requires it.
    """

    corrected = result.copy()
    corrections: list[str] = []
    warnings = list(corrected.warnings)
    if request.workflow_mode == "guided":
        if not result.recommended_operation or not result.recommended_strategy:
            raise StructuredResponseError("AI-guided result must include a recommended operation and strategy")
        if not result.recommended_pass_count or not result.pass_plan:
            raise StructuredResponseError("AI-guided result must include a pass count and at least one pass-plan stage")
    family = tool_family(request.tool_type)
    p = request.parameters
    diameter = _number(p, "diameter_mm", "cutter_diameter_mm")
    if diameter is None or diameter <= 0:
        raise CalculationInputError("Diameter must be greater than 0 mm.")

    if corrected.rpm is None or corrected.rpm <= 0:
        raise StructuredResponseError("Result does not contain a usable RPM")

    if corrected.feed_mm_min is None:
        raise StructuredResponseError("Result does not contain a usable feed")
    source_rpm = corrected.rpm
    constraints = p.get("constraints", {}) if request.workflow_mode == "guided" else {}
    constraints = constraints if isinstance(constraints, dict) else {}
    limit_fields = {
        "max_rpm": ("Maximum RPM", machine.max_rpm),
        "max_feed_mm_min": ("Maximum feed", machine.max_feed_mm_min),
        "max_axial_doc_mm": ("Maximum axial DOC", None),
        "max_radial_engagement_mm": ("Maximum radial engagement", None),
        "max_stepover_mm": ("Maximum stepover", None),
    }
    limits: dict[str, float] = {}
    for key, (label, machine_limit) in limit_fields.items():
        requested = _number({"value": constraints.get(key)}, "value")
        if requested is not None and requested > 0:
            limits[key] = min(requested, machine_limit) if machine_limit is not None else requested
        elif machine_limit is not None:
            limits[key] = machine_limit

    if family in {"drill", "reamer"}:
        if corrected.feed_per_rev_mm is None:
            corrected.feed_per_rev_mm = result.feed_mm_min / source_rpm
            corrections.append("Feed per revolution derived from feed and RPM.")
    elif family == "tap":
        pitch = _number(p, "pitch_mm")
        if pitch is None or pitch <= 0:
            raise CalculationInputError("Pitch must be greater than 0 mm.")
        corrected.tap_pitch_mm = pitch
        rigid_tapping = _enabled(p.get("rigid_tapping"), default=True)
        if rigid_tapping:
            corrected.feed_per_rev_mm = pitch
        elif corrected.feed_per_rev_mm is None:
            corrected.feed_per_rev_mm = result.feed_mm_min / source_rpm
            corrections.append("Feed per revolution derived from feed and RPM.")
    else:
        count = _number(p, "flute_count", "insert_count")
        if (count is None or count < 1) and request.workflow_mode == "guided":
            corrected.feed_per_tooth_mm = None
        elif count is None or count < 1:
            raise CalculationInputError("Flute/insert count must be at least 1.")
        elif corrected.feed_per_tooth_mm is None:
            corrected.feed_per_tooth_mm = result.feed_mm_min / (source_rpm * count)
            corrections.append("Feed per tooth derived from feed, RPM, and tooth count.")

    def recalculate_feed() -> None:
        if family in {"drill", "reamer"}:
            corrected.feed_mm_min = drilling_feed_mm_min(corrected.rpm, corrected.feed_per_rev_mm)
        elif family == "tap":
            if rigid_tapping:
                corrected.feed_mm_min = tapping_feed_mm_min(corrected.rpm, pitch)
            elif corrected.feed_per_rev_mm is not None:
                corrected.feed_mm_min = drilling_feed_mm_min(corrected.rpm, corrected.feed_per_rev_mm)
        elif count is not None and corrected.feed_per_tooth_mm is not None:
            corrected.feed_mm_min = milling_feed_mm_min(corrected.rpm, count, corrected.feed_per_tooth_mm)
        elif request.workflow_mode == "guided" and source_rpm > 0:
            corrected.feed_mm_min = result.feed_mm_min * corrected.rpm / source_rpm

    def limit_label_for(key: str, machine_limit: float) -> str:
        requested = _number({"value": constraints.get(key)}, "value")
        if requested is not None and 0 < requested <= machine_limit:
            return "requested maximum"
        return f"{machine.name} maximum"

    effective_max_rpm = limits["max_rpm"]
    if corrected.rpm > effective_max_rpm:
        corrected.rpm = effective_max_rpm
        limit_label = limit_label_for("max_rpm", machine.max_rpm)
        correction = f"RPM limited locally to the {limit_label} of {effective_max_rpm:g} RPM."
        corrections.append(correction)
        warnings.append(correction)
    recalculate_feed()
    if not _close(result.feed_mm_min, corrected.feed_mm_min):
        if family == "tap" and rigid_tapping:
            corrections.append("Rigid-tap feed recalculated as RPM × exact pitch.")
        elif family in {"drill", "reamer"}:
            corrections.append("Feed recalculated from RPM × feed per revolution.")
        elif family != "tap":
            corrections.append("Milling feed recalculated as RPM × teeth × feed per tooth.")

    if family == "drill":
        validate_drilling_peck(corrected)
        depth = _number(p, "hole_depth_mm")
        if depth is not None and corrected.peck_mm is not None and corrected.peck_mm > depth:
            warnings.append("Peck depth exceeds the entered hole depth; verify the cycle before running.")
        if corrected.peck_recommended is None:
            warnings.append("AI did not specify whether pecking is required; verify the drilling cycle.")
    elif family == "reamer":
        cycle_text = (corrected.recommended_cycle or "").casefold()
        for prohibition in (
            "do not peck",
            "don't peck",
            "no peck",
            "without peck",
            "avoid peck",
            "do not drill",
            "don't drill",
            "no drilling",
            "without drilling",
            "avoid drilling",
        ):
            cycle_text = cycle_text.replace(prohibition, "")
        invalid_cycle_markers = ("peck", "g83", "g81", "drill", "chip-clearing", "chip clearing")
        invalid_cycle = any(marker in cycle_text for marker in invalid_cycle_markers)
        had_peck_fields = corrected.peck_mm is not None or corrected.peck_recommended is True
        if had_peck_fields or invalid_cycle:
            # Pecking is not an applicable Reamer output. Discard only the
            # incompatible fields rather than manufacturing a replacement
            # cycle or refusing otherwise usable reaming data.
            corrected.peck_mm = None
            corrected.peck_recommended = False
            if invalid_cycle:
                corrected.recommended_cycle = None
            corrections.append("Incompatible Reamer peck data discarded locally; use continuous-feed reaming.")
            warnings.append(
                "AI returned drilling-style peck data for a Reamer; the peck data was discarded. "
                "Use continuous-feed reaming and verify the cycle before running."
            )
        if corrected.pre_ream_size_mm is None:
            warnings.append("AI did not provide a pre-ream size; verify the bore preparation.")
        if corrected.reaming_stock_mm is None:
            warnings.append("AI did not provide reaming stock; verify the bore preparation.")
    elif family == "tap":
        if pitch >= diameter:
            warnings.append("Pitch is unusually large relative to the nominal thread diameter; verify the thread data.")
        if corrected.tap_drill_mm is None:
            warnings.append("AI did not provide a tapping drill size; verify the thread and tap type.")

    effective_max_feed = limits["max_feed_mm_min"]
    if corrected.feed_mm_min > effective_max_feed:
        if family == "tap" and rigid_tapping:
            feed_per_rpm = pitch
            relationship = "RPM × exact pitch"
        elif family in {"drill", "reamer", "tap"}:
            feed_per_rpm = corrected.feed_per_rev_mm
            relationship = "RPM × feed per revolution"
        elif count is None and request.workflow_mode == "guided":
            corrected.feed_mm_min = effective_max_feed
            limit_label = limit_label_for("max_feed_mm_min", machine.max_feed_mm_min)
            correction = f"Feed limited locally to the {limit_label} of {effective_max_feed:g} mm/min because tool tooth count is unknown."
            corrections.append(correction)
            warnings.append(correction)
            feed_per_rpm = None
            relationship = "unknown tooth count"
        else:
            feed_per_rpm = corrected.feed_per_tooth_mm * count
            relationship = "RPM × teeth × feed per tooth"
        if feed_per_rpm is None and request.workflow_mode == "guided" and count is None:
            pass
        elif feed_per_rpm is None or feed_per_rpm <= 0:
            raise StructuredResponseError("Feed exceeds the machine limit but has no valid dependent relationship")
        else:
            allowed_rpm = effective_max_feed / feed_per_rpm
            if allowed_rpm <= 0:
                raise StructuredResponseError("Machine feed limit cannot support the returned feed relationship")
            if allowed_rpm < corrected.rpm:
                corrected.rpm = allowed_rpm
                correction = (
                    f"RPM reduced locally to {allowed_rpm:g} to stay within the {machine.name} feed limit "
                    f"while preserving {relationship}."
                )
                corrections.append(correction)
                warnings.append(correction)
                recalculate_feed()

    for index, stage in enumerate(corrected.pass_plan):
        stage_rpm = _number(stage, "rpm")
        stage_feed = _number(stage, "feed_mm_min")
        # Scale the stage's RPM and feed together so a local limit never
        # changes the feed per tooth/rev the model chose for that pass.
        if stage_rpm is not None and stage_rpm > effective_max_rpm:
            if stage_feed is not None and stage_rpm > 0:
                stage_feed = stage_feed * effective_max_rpm / stage_rpm
                stage["feed_mm_min"] = stage_feed
            stage_rpm = effective_max_rpm
            stage["rpm"] = stage_rpm
            message = f"Pass {index + 1} RPM limited locally to {effective_max_rpm:g} RPM" + (
                "; feed reduced in proportion." if stage_feed is not None else "."
            )
            corrections.append(message)
            warnings.append(message)
        if stage_feed is not None and stage_feed > effective_max_feed:
            if stage_rpm is not None and stage_feed > 0:
                stage["rpm"] = stage_rpm * effective_max_feed / stage_feed
            stage["feed_mm_min"] = effective_max_feed
            message = f"Pass {index + 1} feed limited locally to {effective_max_feed:g} mm/min" + (
                "; RPM reduced in proportion." if stage_rpm is not None else "."
            )
            corrections.append(message)
            warnings.append(message)
        for result_key, constraint_key, stage_key in (
            ("axial_doc_mm", "max_axial_doc_mm", "axial_doc_mm"),
            ("radial_doc_mm", "max_radial_engagement_mm", "radial_engagement_mm"),
            ("stepover_mm", "max_stepover_mm", "stepover_mm"),
        ):
            maximum = limits.get(constraint_key)
            stage_value = _number(stage, stage_key)
            if maximum is not None and stage_value is not None and stage_value > maximum:
                stage[stage_key] = maximum
                message = f"Pass {index + 1} {stage_key.replace('_', ' ')} limited locally to the requested {maximum:g} mm maximum."
                corrections.append(message)
                warnings.append(message)

    for result_key, constraint_key, label in (
        ("axial_doc_mm", "max_axial_doc_mm", "axial DOC"),
        ("radial_doc_mm", "max_radial_engagement_mm", "radial engagement"),
        ("stepover_mm", "max_stepover_mm", "stepover"),
    ):
        maximum = limits.get(constraint_key)
        actual = getattr(corrected, result_key)
        if maximum is not None and actual is not None and actual > maximum:
            setattr(corrected, result_key, maximum)
            message = f"{label.title()} limited locally to the requested {maximum:g} mm maximum."
            corrections.append(message)
            warnings.append(message)

    expected_speed = cutting_speed_m_min(diameter, corrected.rpm)
    if not _close(result.cutting_speed_m_min, expected_speed):
        corrected.cutting_speed_m_min = expected_speed
        corrections.append("Cutting speed recalculated from diameter and RPM.")

    corrected.warnings = list(dict.fromkeys(warnings))
    return corrected, corrections


class CalculationService:
    """Cache-first orchestration shared by every tool family."""

    def __init__(
        self,
        database: Database,
        ai_service: Any,
        progress_callback: Callable[[str], None] | None = None,
        independent_check: bool = True,
    ):
        self.database = database
        self.ai_service = ai_service
        self.progress_callback = progress_callback
        # False gives a quicker Guided result from the first AI call only.
        self.independent_check = independent_check
        # The UI uses this read-only context when a response cannot become a
        # CalculationOutcome. It deliberately contains no API credentials.
        self.last_failure_context: dict[str, Any] = {}

    def _progress(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)

    def calculate(self, request: MachiningRequest, machine: MachineProfile) -> CalculationOutcome:
        request = replace(request, parameters=active_parameters(request.tool_type, request.operation, request.parameters))
        guided = request.workflow_mode == "guided" or request.operation.strip().casefold() == "ai guided"
        if guided and not getattr(self.ai_service, "is_mock", False):
            request = replace(
                request,
                comparison_history=related_calculation_history(self.database, request),
            )
        normalized = normalize_request(request)
        request_key = request_hash(normalized)
        selected_model = str(getattr(self.ai_service, "model", "") or "")
        cache_key = model_cache_identity(normalized, selected_model)
        self.last_failure_context = {
            "normalized_request": normalized,
            "request_hash": request_key,
            "cache_identity": cache_key,
            "source": "mock" if getattr(self.ai_service, "is_mock", False) else "ai",
            "model": selected_model,
            "prompt": build_user_prompt(request, machine),
            "raw_response": "",
            "validated_response": "",
            "response_id": "",
            "usage": {},
            "stage": "request validation",
        }
        errors, input_warnings = validate_request(request, machine)
        if errors:
            raise CalculationInputError(" ".join(errors))

        # Workshop preferences intentionally follow only the exact machining
        # request and continue to apply when the selected model changes.
        preferred = self.database.get_preferred_result(request_key)
        if preferred:
            self.last_failure_context.update(
                {
                    "source": "workshop",
                    "model": "local workshop setting",
                    "raw_response": preferred["ai_result_json"],
                    "stage": "workshop result validation",
                }
            )
            preferred_result = result_from_json(preferred["preferred_result_json"])
            validated, corrections = validate_and_correct_result(preferred_result, request, machine)
            validated.warnings = list(dict.fromkeys(input_warnings + validated.warnings))
            return CalculationOutcome(
                result=validated,
                normalized_request=normalized,
                request_hash=request_key,
                source="workshop",
                cache_hit=True,
                model="local workshop setting",
                prompt="",
                raw_response=preferred["ai_result_json"],
                validated_response=json.dumps(validated.to_dict(), ensure_ascii=False, sort_keys=True),
                validation_corrections=corrections,
            )

        cached = None
        if not getattr(self.ai_service, "is_mock", False):
            cached = self.database.get_cache_record(cache_key, model=selected_model)
        if cached:
            try:
                self.last_failure_context.update(
                    {
                        "source": "cache",
                        "model": cached["model"],
                        "raw_response": cached["returned_data_json"],
                        "response_id": cached.get("response_id", ""),
                        "usage": json.loads(cached.get("usage_json", "{}")),
                        "stage": "cached result validation",
                    }
                )
                cached_result = result_from_json(cached["validated_data_json"])
                cached_status = cached_result.verification_status
                if guided and (
                    cached_status == "check_incomplete"
                    or (self.independent_check and cached_status not in {"cross_checked", "review_required"})
                ):
                    # An unchecked entry (a quick result, or one cached by an
                    # earlier release before the check finished) must not
                    # stand in for a fully checked calculation.
                    raise StructuredResponseError("Cached result has no completed independent check")
                validated, corrections = validate_and_correct_result(cached_result, request, machine)
            except (StructuredResponseError, CalculationInputError):
                cached = None
            else:
                validated.warnings = list(dict.fromkeys(input_warnings + validated.warnings))
                return CalculationOutcome(
                    result=validated,
                    normalized_request=normalized,
                    request_hash=request_key,
                    source="cache",
                    cache_hit=True,
                    model=cached["model"],
                    raw_response=cached["returned_data_json"],
                    validated_response=json.dumps(validated.to_dict(), ensure_ascii=False, sort_keys=True),
                    response_id=cached.get("response_id", ""),
                    usage=json.loads(cached.get("usage_json", "{}")),
                    validation_corrections=corrections,
                )

        self.last_failure_context["stage"] = "AI research"
        self._progress("Researching tool, material and machining strategy")
        service_response: ServiceResponse = self.ai_service.calculate(request, machine)
        self._progress("Validating speeds, feeds and machine limits")
        self.last_failure_context.update(
            {
                "source": "mock" if service_response.is_mock else "ai",
                "model": service_response.model,
                "prompt": service_response.prompt,
                "raw_response": service_response.raw_text,
                "response_id": service_response.response_id,
                "usage": service_response.usage or {},
                "stage": "structured response validation",
                "research_status": service_response.research_status,
                "research_sources": service_response.research_sources or [],
            }
        )
        model_result = result_from_dict(service_response.payload)
        validated, corrections = validate_and_correct_result(model_result, request, machine)
        validated.warnings = list(dict.fromkeys(input_warnings + validated.warnings))

        primary_sources = list(service_response.research_sources or [])
        validated.research_sources = primary_sources
        validated.research_status = service_response.research_status
        continuity_findings = small_depth_change_findings(request, validated.to_dict()) if guided else []
        validated.history_comparison = continuity_findings

        reviewer_response = None
        verification_error = ""
        verifier = getattr(self.ai_service, "verify", None)
        if guided and self.independent_check and not service_response.is_mock and callable(verifier):
            self.last_failure_context["stage"] = "independent check"
            self._progress("Independently checking the recommendation")
            try:
                reviewer_response = verifier(
                    request,
                    machine,
                    validated.to_dict(),
                    continuity_findings=continuity_findings,
                    validation_corrections=corrections,
                    research_sources=primary_sources,
                )
            except Exception as exc:
                verification_error = "timeout" if isinstance(exc, OpenAIServiceError) and "timed out" in str(exc) else type(exc).__name__
                self.last_failure_context.update(
                    {
                        "verification_error": verification_error,
                        "verification_status": "check_incomplete",
                    }
                )

        verification_usage: dict[str, Any] = {}
        if guided and not service_response.is_mock:
            if reviewer_response is None:
                if self.independent_check:
                    validated.verification_status = "check_incomplete"
                    detail = f" ({verification_error})" if verification_error else ""
                    validated.verification_summary = (
                        "The independent check did not complete"
                        + detail
                        + "; treat this recommendation as unverified."
                    )
                    validated.warnings.append(validated.verification_summary)
                    validated.confidence = "low"
                else:
                    validated.warnings.append(
                        "Quick calculation: the independent AI check was not run."
                    )
                if primary_sources:
                    validated.research_status = "searched"
                elif service_response.research_status in {"unavailable", "no_sources"}:
                    validated.research_status = service_response.research_status
                    validated.warnings.append(
                        "No current web-search source was verified for this calculation."
                    )
                else:
                    validated.research_status = "not_used"
                    validated.warnings.append(
                        "No web-search citations were available for this calculation."
                    )
            else:
                report = reviewer_response.payload
                report_status = report.get("status")
                history_assessment = report.get("history_change_assessment", "unclear")
                history_reason = str(report.get("history_change_reason") or "").strip()
                validated.verification_summary = str(report.get("summary") or "Independent check returned no summary.")
                findings = report.get("findings", [])
                validated.verification_findings = [str(item) for item in findings if isinstance(item, str)][:8] if isinstance(findings, list) else []
                if continuity_findings and history_reason:
                    validated.verification_findings.append(
                        "History change rationale: " + history_reason[:500]
                    )
                validated.verification_response_id = reviewer_response.response_id
                validation_status_ok = report_status == "consistent"
                history_change_ok = not continuity_findings or (
                    history_assessment == "justified" and bool(history_reason)
                )
                if validation_status_ok and history_change_ok:
                    validated.verification_status = "cross_checked"
                else:
                    validated.verification_status = "review_required"
                    validated.confidence = "low"
                    validated.warnings.append(
                        "Independent check requires operator review: " + validated.verification_summary
                    )
                    validated.warnings.extend(validated.verification_findings)

                reviewer_sources = list(reviewer_response.research_sources or [])
                validated.research_sources = _merge_research_sources(primary_sources, reviewer_sources)
                search_statuses = {service_response.research_status, reviewer_response.research_status}
                if validated.research_sources:
                    validated.research_status = "searched"
                elif "unavailable" in search_statuses:
                    validated.research_status = "unavailable"
                    validated.warnings.append(
                        "Live web research was unavailable; no current external source was verified."
                    )
                elif "no_sources" in search_statuses:
                    validated.research_status = "no_sources"
                    validated.warnings.append(
                        "Web search returned no usable citations for this setup; key tool/material facts remain unverified."
                    )
                else:
                    validated.research_status = "not_used"
                    validated.warnings.append(
                        "The model did not return web-search citations; key tool/material facts remain unverified."
                    )
                self.last_failure_context.update(
                    {
                        "verification_prompt": reviewer_response.prompt,
                        "verification_raw_response": reviewer_response.raw_text,
                        "verification_response_id": reviewer_response.response_id,
                        "verification_status": validated.verification_status,
                        "verification_findings": validated.verification_findings,
                        "research_status": validated.research_status,
                        "research_sources": validated.research_sources,
                    }
                )
                verification_usage = reviewer_response.usage or {}

        self._progress("Finishing the result")
        validated.warnings = list(dict.fromkeys(validated.warnings))
        combined_usage = _combine_usage(service_response.usage or {}, verification_usage)
        validated_json = json.dumps(validated.to_dict(), ensure_ascii=False, sort_keys=True)

        if not service_response.is_mock:
            actual_cache_key = model_cache_identity(normalized, service_response.model)
            self.last_failure_context["cache_identity"] = actual_cache_key
            # An incomplete independent check is not cached, so repeating the
            # calculation retries the check instead of replaying this result.
            if validated.verification_status != "check_incomplete":
                self.database.put_cache_record(
                    request_hash=actual_cache_key,
                    normalized_request=normalized,
                    returned_data=service_response.payload,
                    validated_data=validated.to_dict(),
                    model=service_response.model,
                    response_id=service_response.response_id,
                    usage=combined_usage,
                )
            self.database.add_recent(
                request_key, normalized, validated.to_dict(), "ai", model=service_response.model
            )

        return CalculationOutcome(
            result=validated,
            normalized_request=normalized,
            request_hash=request_key,
            source="mock" if service_response.is_mock else "ai",
            cache_hit=False,
            model=service_response.model,
            prompt=service_response.prompt,
            raw_response=service_response.raw_text,
            validated_response=validated_json,
            response_id=service_response.response_id,
            usage=combined_usage,
            validation_corrections=corrections,
            verification_prompt=reviewer_response.prompt if reviewer_response else "",
            verification_raw_response=reviewer_response.raw_text if reviewer_response else "",
        )

    def save_workshop_preference(
        self,
        outcome: CalculationOutcome,
        preferred_result: MachiningResult,
    ) -> None:
        if outcome.source == "mock":
            raise CalculationInputError("Mock results cannot be saved as workshop settings.")
        ai_json = outcome.raw_response or outcome.validated_response
        try:
            ai_payload = json.loads(ai_json)
        except json.JSONDecodeError:
            ai_payload = outcome.result.to_dict()
        self.database.save_preferred_result(
            outcome.request_hash,
            outcome.normalized_request,
            ai_payload,
            preferred_result.to_dict(),
        )
