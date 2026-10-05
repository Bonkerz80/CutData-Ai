"""Canonical request normalisation and deterministic cache keys."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from ..models.domain import MachiningRequest
from ..config.operations import active_parameters
from ..config.constants import PROMPT_VERSION, SCHEMA_VERSION


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
    return hashlib.sha256(canonical_json(_machining_identity(normalized_request)).encode("utf-8")).hexdigest()


def _machining_identity(normalized_request: dict[str, Any]) -> dict[str, Any]:
    """Drop library labels/revisions while retaining facts used for advice."""
    value = json.loads(canonical_json(normalized_request))
    # Comparison history changes the model's context, not the physical job's
    # identity (or any saved workshop preference keyed to that job).
    value.pop("comparison_history", None)
    snapshot = value.get("tool_snapshot")
    if isinstance(snapshot, dict):
        for key in ("display_name", "library_id", "revision", "seed_key", "created_at", "updated_at", "user_modified"):
            snapshot.pop(key, None)
        _drop_display_name_provenance(snapshot)
        insert = snapshot.get("insert")
        if isinstance(insert, dict):
            for key in ("display_name", "library_id", "revision", "seed_key", "created_at", "updated_at", "user_modified"):
                insert.pop(key, None)
            _drop_display_name_provenance(insert)
    return value


def _drop_display_name_provenance(record: dict[str, Any]) -> None:
    provenance = record.get("field_provenance")
    if isinstance(provenance, dict):
        provenance.pop("display_name", None)


def model_cache_identity(
    normalized_request: dict[str, Any],
    model: str,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    """Identify production cache entries by request, model, and contract version.

    Keep ``request_hash`` model-independent: workshop preferences and recent
    history use it to identify the exact machining request itself.
    """

    identity = {
        "machining_request": _machining_identity(normalized_request),
        "comparison_history": normalized_request.get("comparison_history", []),
        "model": str(model),
        "prompt_version": str(prompt_version),
        "schema_version": str(schema_version),
    }
    return hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
