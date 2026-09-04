"""Local validation, arithmetic correction, and cache-aware calculation flow."""

from __future__ import annotations

import json
import math
from typing import Any

from ..config.constants import tool_family
from ..database.database import Database
from ..models.domain import CalculationOutcome, MachiningRequest, MachiningResult, MachineProfile
from ..models.schema import StructuredResponseError, result_from_dict, result_from_json
from .normalization import normalize_request, request_hash
from .openai_service import ServiceResponse


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
    if family in {"end_mill", "indexable"} and (count is None or count < 1 or count > 100):
        errors.append("Enter a sensible flute or insert count (at least 1).")

    if family == "tap":
        pitch = _number(p, "pitch_mm")
        if pitch is None or pitch <= 0:
            errors.append("Enter a pitch greater than 0 mm.")

    if request.hardness_hrc is not None and request.hardness_hrc < 0:
        errors.append("Hardness cannot be negative.")
    if request.hardness_hrc is not None and request.hardness_hrc > 70:
        warnings.append("Hardness is above the usual HRC range; confirm the material specification.")

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
        if count is None or count < 1:
            raise CalculationInputError("Flute/insert count must be at least 1.")
        if corrected.feed_per_tooth_mm is None:
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
        else:
            corrected.feed_mm_min = milling_feed_mm_min(corrected.rpm, count, corrected.feed_per_tooth_mm)

    if corrected.rpm > machine.max_rpm:
        corrected.rpm = machine.max_rpm
        correction = f"RPM limited locally to the {machine.name} maximum of {machine.max_rpm:g} RPM."
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
        if corrected.peck_recommended is not None and not isinstance(corrected.peck_recommended, bool):
            raise StructuredResponseError("Peck recommendation must be boolean or null")
        if corrected.peck_recommended is True and (corrected.peck_mm is None or corrected.peck_mm <= 0):
            raise StructuredResponseError("Pecking was recommended but no positive peck depth was provided")
        depth = _number(p, "hole_depth_mm")
        if depth is not None and corrected.peck_mm is not None and corrected.peck_mm > depth:
            warnings.append("Peck depth exceeds the entered hole depth; verify the cycle before running.")
        if corrected.peck_recommended is None:
            warnings.append("AI did not specify whether pecking is required; verify the drilling cycle.")
    elif family == "reamer":
        if corrected.peck_recommended is True or (
            corrected.recommended_cycle and "peck" in corrected.recommended_cycle.casefold()
        ):
            raise StructuredResponseError("Reamer response requested a drilling-style peck cycle")
        if corrected.pre_ream_size_mm is None:
            warnings.append("AI did not provide a pre-ream size; verify the bore preparation.")
        if corrected.reaming_stock_mm is None:
            warnings.append("AI did not provide reaming stock; verify the bore preparation.")
    elif family == "tap":
        if pitch >= diameter:
            warnings.append("Pitch is unusually large relative to the nominal thread diameter; verify the thread data.")
        if corrected.tap_drill_mm is None:
            warnings.append("AI did not provide a tapping drill size; verify the thread and tap type.")

    if corrected.feed_mm_min > machine.max_feed_mm_min:
        if family == "tap" and rigid_tapping:
            feed_per_rpm = pitch
            relationship = "RPM × exact pitch"
        elif family in {"drill", "reamer", "tap"}:
            feed_per_rpm = corrected.feed_per_rev_mm
            relationship = "RPM × feed per revolution"
        else:
            feed_per_rpm = corrected.feed_per_tooth_mm * count
            relationship = "RPM × teeth × feed per tooth"
        if feed_per_rpm is None or feed_per_rpm <= 0:
            raise StructuredResponseError("Feed exceeds the machine limit but has no valid dependent relationship")
        allowed_rpm = machine.max_feed_mm_min / feed_per_rpm
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

    expected_speed = cutting_speed_m_min(diameter, corrected.rpm)
    if not _close(result.cutting_speed_m_min, expected_speed):
        corrected.cutting_speed_m_min = expected_speed
        corrections.append("Cutting speed recalculated from diameter and RPM.")

    corrected.warnings = list(dict.fromkeys(warnings))
    return corrected, corrections


class CalculationService:
    """Cache-first orchestration shared by every tool family."""

    def __init__(self, database: Database, ai_service: Any):
        self.database = database
        self.ai_service = ai_service

    def calculate(self, request: MachiningRequest, machine: MachineProfile) -> CalculationOutcome:
        errors, input_warnings = validate_request(request, machine)
        if errors:
            raise CalculationInputError(" ".join(errors))

        normalized = normalize_request(request)
        cache_key = request_hash(normalized)

        preferred = self.database.get_preferred_result(cache_key)
        if preferred:
            preferred_result = result_from_json(preferred["preferred_result_json"])
            validated, corrections = validate_and_correct_result(preferred_result, request, machine)
            validated.warnings = list(dict.fromkeys(input_warnings + validated.warnings))
            return CalculationOutcome(
                result=validated,
                normalized_request=normalized,
                request_hash=cache_key,
                source="workshop",
                cache_hit=True,
                model="local workshop setting",
                prompt="",
                raw_response=preferred["ai_result_json"],
                validated_response=json.dumps(validated.to_dict(), ensure_ascii=False, sort_keys=True),
                validation_corrections=corrections,
            )

        cached = self.database.get_cache_record(cache_key)
        if cached:
            try:
                cached_result = result_from_json(cached["validated_data_json"])
                validated, corrections = validate_and_correct_result(cached_result, request, machine)
            except (StructuredResponseError, CalculationInputError):
                cached = None
            else:
                validated.warnings = list(dict.fromkeys(input_warnings + validated.warnings))
                return CalculationOutcome(
                    result=validated,
                    normalized_request=normalized,
                    request_hash=cache_key,
                    source="cache",
                    cache_hit=True,
                    model=cached["model"],
                    raw_response=cached["returned_data_json"],
                    validated_response=json.dumps(validated.to_dict(), ensure_ascii=False, sort_keys=True),
                    response_id=cached.get("response_id", ""),
                    usage=json.loads(cached.get("usage_json", "{}")),
                    validation_corrections=corrections,
                )

        service_response: ServiceResponse = self.ai_service.calculate(request, machine)
        model_result = result_from_dict(service_response.payload)
        validated, corrections = validate_and_correct_result(model_result, request, machine)
        validated.warnings = list(dict.fromkeys(input_warnings + validated.warnings))
        validated_json = json.dumps(validated.to_dict(), ensure_ascii=False, sort_keys=True)

        if not service_response.is_mock:
            self.database.put_cache_record(
                request_hash=cache_key,
                normalized_request=normalized,
                returned_data=service_response.payload,
                validated_data=validated.to_dict(),
                model=service_response.model,
                response_id=service_response.response_id,
                usage=service_response.usage or {},
            )
            self.database.add_recent(cache_key, normalized, validated.to_dict(), "ai")

        return CalculationOutcome(
            result=validated,
            normalized_request=normalized,
            request_hash=cache_key,
            source="mock" if service_response.is_mock else "ai",
            cache_hit=False,
            model=service_response.model,
            prompt=service_response.prompt,
            raw_response=service_response.raw_text,
            validated_response=validated_json,
            response_id=service_response.response_id,
            usage=service_response.usage or {},
            validation_corrections=corrections,
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
