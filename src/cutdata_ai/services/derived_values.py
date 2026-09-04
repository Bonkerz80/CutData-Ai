"""Pure display-only calculations derived from an AI result and known inputs."""

from __future__ import annotations

import math


def _positive(value: float | int | None) -> float | None:
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    if number is None or not math.isfinite(number) or number <= 0:
        return None
    return number


def hole_ld_ratio(depth_mm: float | None, diameter_mm: float | None) -> float | None:
    depth = _positive(depth_mm)
    diameter = _positive(diameter_mm)
    return depth / diameter if depth is not None and diameter is not None else None


def radial_engagement_percent(radial_doc_mm: float | None, diameter_mm: float | None) -> float | None:
    radial = _positive(radial_doc_mm)
    diameter = _positive(diameter_mm)
    return radial / diameter * 100.0 if radial is not None and diameter is not None else None


def axial_doc_ratio(axial_doc_mm: float | None, diameter_mm: float | None) -> float | None:
    axial = _positive(axial_doc_mm)
    diameter = _positive(diameter_mm)
    return axial / diameter if axial is not None and diameter is not None else None


def material_removal_rate_cm3_min(
    axial_doc_mm: float | None,
    radial_doc_mm: float | None,
    feed_mm_min: float | None,
) -> float | None:
    axial = _positive(axial_doc_mm)
    radial = _positive(radial_doc_mm)
    feed = _positive(feed_mm_min)
    return axial * radial * feed / 1000.0 if axial and radial and feed else None


def usage_percent(actual: float | None, maximum: float | None) -> float | None:
    actual_value = _positive(actual)
    maximum_value = _positive(maximum)
    return actual_value / maximum_value * 100.0 if actual_value is not None and maximum_value is not None else None


def torque_from_power(power_kw: float | None, rpm: float | None) -> float | None:
    power = _positive(power_kw)
    speed = _positive(rpm)
    return 9550.0 * power / speed if power is not None and speed is not None else None
