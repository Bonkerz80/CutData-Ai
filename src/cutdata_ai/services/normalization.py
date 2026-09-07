"""Canonical request normalisation and deterministic cache keys."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from ..models.domain import MachiningRequest
from ..config.operations import active_parameters


def _normalise_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key).strip().casefold(): _normalise_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_normalise_value(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Machining request contains a non-finite number")
        rounded = round(number, 6)
        return int(rounded) if rounded.is_integer() else rounded
    if isinstance(value, str):
        # Labels come from controlled lists, while free-text fields may contain
        # inconsistent casing/spacing. Both should cache as the same request.
        return " ".join(value.strip().casefold().split())
    return str(value).strip().casefold()


def normalize_request(request: MachiningRequest) -> dict[str, Any]:
    """Return a stable, JSON-compatible representation of a request."""

    value = request.to_dict()
    value["parameters"] = active_parameters(request.tool_type, request.operation, request.parameters)
    return _normalise_value(value)


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_hash(normalized_request: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(normalized_request).encode("utf-8")).hexdigest()
