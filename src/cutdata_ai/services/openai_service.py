"""OpenAI Responses API integration and deterministic development mode."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from ..config.constants import DEFAULT_MODEL, model_display_name
from ..models.domain import MachiningRequest, MachineProfile
from ..models.schema import StructuredResponseError
from ..prompts.machining import SYSTEM_PROMPT, build_user_prompt, schema_for_openai


class OpenAIServiceError(RuntimeError):
    """An API or response transport error suitable for display in the UI."""


@dataclass(frozen=True)
class ConnectionTestResult:
    """A user-facing connection result with optional non-secret diagnostics."""

    success: bool
    category: str
    message: str
    technical_detail: str = ""

    @property
    def ok(self) -> bool:
        """Alias that reads naturally at call sites and in tests."""

        return self.success


def _exception_status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def connection_result_for_exception(exc: Exception, model: str) -> ConnectionTestResult:
    """Map SDK failures to clean messages without echoing exception details."""

    status_code = _exception_status_code(exc)
    name = type(exc).__name__.casefold()
    if status_code == 401 or any(token in name for token in ("authentication", "unauthorized")):
        category = "authentication"
        message = "Authentication failed\nCheck your OpenAI API key."
    elif status_code in {400, 403, 404} or any(
        token in name for token in ("permission", "notfound", "model")
    ):
        category = "model_unavailable"
        message = (
            "Model unavailable\n"
            f"The API key works, but {model_display_name(model)} is not available to this account."
        )
    else:
        category = "network"
        message = "Network error\nUnable to reach OpenAI."
    detail = type(exc).__name__
    if status_code is not None:
        detail += f" (HTTP {status_code})"
    return ConnectionTestResult(False, category, message, detail)


@dataclass
class ServiceResponse:
    payload: dict[str, Any]
    raw_text: str
    prompt: str
    model: str
    response_id: str = ""
    usage: dict[str, Any] | None = None
    is_mock: bool = False


def _as_plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _as_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_plain(item) for item in value]
    if hasattr(value, "model_dump"):
        return _as_plain(value.model_dump())
    if hasattr(value, "__dict__"):
        return _as_plain(vars(value))
    return str(value)


def _extract_payload(response: Any) -> tuple[dict[str, Any], str]:
    """Extract JSON from the SDK response without scraping prose."""

    candidates: list[str] = []
    if isinstance(response, dict):
        output_text = response.get("output_text")
    else:
        output_text = getattr(response, "output_text", None)
    if output_text:
        candidates.append(str(output_text))

    output = response.get("output") if isinstance(response, dict) else getattr(response, "output", None)
    for item in output or []:
        item_content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
        for content in item_content or []:
            content_type = content.get("type") if isinstance(content, dict) else getattr(content, "type", None)
            if content_type in {"output_text", "text"}:
                text = content.get("text") if isinstance(content, dict) else getattr(content, "text", None)
                if text:
                    candidates.append(str(text))

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload, candidate
    raise OpenAIServiceError("OpenAI returned no valid structured machining result")


class OpenAIService:
    """Thin wrapper around the official OpenAI Python SDK Responses API."""

    is_mock = False

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        reasoning_effort: str = "medium",
        client: Any | None = None,
    ):
        if not api_key and client is None:
            raise OpenAIServiceError("No OpenAI API key is configured")
        self.model = model
        self.reasoning_effort = reasoning_effort
        if client is not None:
            self.client = client
        else:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise OpenAIServiceError("The OpenAI package is not installed") from exc
            self.client = OpenAI(api_key=api_key, timeout=90.0, max_retries=2)

    def test_connection(self) -> ConnectionTestResult:
        """Verify key authentication and selected-model access with no tokens.

        The Models retrieve endpoint is preferred because it does not create a
        response or consume model output tokens.  The tiny Responses fallback
        keeps this compatible with minimal test doubles and older SDK clients.
        """

        try:
            models = getattr(self.client, "models", None)
            retrieve = getattr(models, "retrieve", None)
            if callable(retrieve):
                retrieve(self.model)
            else:
                self.client.responses.create(
                    model=self.model,
                    input="OK",
                    reasoning={"effort": "low"},
                    max_output_tokens=1,
                )
        except Exception as exc:
            return connection_result_for_exception(exc, self.model)
        return ConnectionTestResult(
            True,
            "success",
            f"Connection successful\n{model_display_name(self.model)} is available.",
        )

    def calculate(self, request: MachiningRequest, machine: MachineProfile) -> ServiceResponse:
        prompt = build_user_prompt(request, machine)
        try:
            response = self.client.responses.create(
                model=self.model,
                reasoning={"effort": self.reasoning_effort},
                input=[
                    {
                        "role": "developer",
                        "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": prompt}],
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "machining_result",
                        "strict": True,
                        "schema": schema_for_openai(),
                    }
                },
            )
        except Exception as exc:
            # Do not include the key or the full request in the exception text.
            raise OpenAIServiceError(f"OpenAI request failed: {exc}") from exc

        payload, raw_text = _extract_payload(response)
        usage = _as_plain(getattr(response, "usage", None))
        if not isinstance(usage, dict):
            usage = {}
        return ServiceResponse(
            payload=payload,
            raw_text=raw_text,
            prompt=prompt,
            model=self.model,
            response_id=str(getattr(response, "id", "") or ""),
            usage=usage,
        )


class UnavailableOpenAIService:
    """Lazy failure used so cache hits still work without an API key."""

    is_mock = False

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(
            False,
            "no_key",
            "No API key configured\nEnter a key or set OPENAI_API_KEY in Settings.",
        )

    def calculate(self, request: MachiningRequest, machine: MachineProfile) -> ServiceResponse:
        raise OpenAIServiceError("No API key is configured. Open Settings or enable development/mock mode.")


def _material_group(material: str) -> str:
    value = material.casefold()
    if "aluminium" in value or "brass" in value or "bronze" in value or "copper" in value:
        return "nonferrous"
    if "stainless" in value or "17-4" in value:
        return "stainless"
    if "hardened" in value or "toolox 44" in value:
        return "hardened"
    if "cast iron" in value:
        return "cast_iron"
    return "steel"


def _material_speed(material: str, tool_material: str, family: str, operation: str) -> float:
    group = _material_group(material)
    carbide = "carbide" in tool_material.casefold()
    hss_co = "cobalt" in tool_material.casefold() or "hss-co" in tool_material.casefold()
    if family == "tap":
        base = {"nonferrous": 12.0, "stainless": 5.0, "hardened": 3.0, "cast_iron": 6.0, "steel": 8.0}[group]
        return base * (1.25 if carbide else 1.0)
    if family == "reamer":
        base = {"nonferrous": 35.0, "stainless": 8.0, "hardened": 5.0, "cast_iron": 12.0, "steel": 18.0}[group]
        return base * (1.4 if carbide else 1.0)
    if family == "drill":
        base = {"nonferrous": 55.0, "stainless": 14.0, "hardened": 8.0, "cast_iron": 22.0, "steel": 24.0}[group]
        if carbide:
            base *= 2.8
        elif hss_co:
            base *= 1.25
        return base
    base = {"nonferrous": 160.0, "stainless": 65.0, "hardened": 35.0, "cast_iron": 90.0, "steel": 105.0}[group]
    if carbide:
        base *= 1.0
    else:
        base *= 0.35
    if operation.casefold() in {"slotting", "plunging"}:
        base *= 0.7
    if operation.casefold() in {"finishing", "ramp"}:
        base *= 0.9
    return base


def _rpm_for_speed(diameter: float, speed: float, max_rpm: float) -> float:
    if diameter <= 0:
        return 100.0
    raw = speed * 1000.0 / (math.pi * diameter)
    stepped = max(50.0, round(raw / 50.0) * 50.0)
    return min(stepped, max_rpm)


def _coolant(parameters: dict[str, Any], default: str = "Flood coolant") -> str:
    if parameters.get("coolant_type"):
        return str(parameters["coolant_type"])
    if parameters.get("flood_coolant") is True:
        return "Flood coolant"
    if parameters.get("internal_coolant") is True:
        return "Through-tool coolant"
    return default


def _metric_tap_drill(thread_size: str, pitch: float) -> float | None:
    match = re.search(r"(?:m|M)\s*(\d+(?:\.\d+)?)", thread_size or "")
    if not match:
        return None
    return max(0.1, float(match.group(1)) - pitch)


class MockOpenAIService:
    """Offline, visibly non-production responses used for development.

    The calculation service deliberately does not write ``is_mock`` results to
    the production cache.
    """

    is_mock = True

    def __init__(self, model: str = DEFAULT_MODEL, reasoning_effort: str = "medium"):
        self.model = model
        self.reasoning_effort = reasoning_effort

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(
            False,
            "mock",
            "Mock mode is active\nSwitch to LIVE AI MODE to test the OpenAI connection.",
        )

    def calculate(self, request: MachiningRequest, machine: MachineProfile) -> ServiceResponse:
        family = request.tool_type
        from ..config.constants import tool_family

        family = tool_family(family)
        p = request.parameters
        diameter = float(p.get("diameter_mm", p.get("cutter_diameter_mm", 10.0)) or 10.0)
        tool_material = str(p.get("tool_material", p.get("tool_grade", "Carbide")))
        speed = _material_speed(request.material, tool_material, family, request.operation)
        rpm = _rpm_for_speed(diameter, speed, machine.max_rpm)
        payload: dict[str, Any] = {
            "rpm": rpm,
            "cutting_speed_m_min": None,
            "feed_mm_min": None,
            "feed_per_tooth_mm": None,
            "feed_per_rev_mm": None,
            "peck_mm": None,
            "peck_recommended": None,
            "recommended_cycle": None,
            "axial_doc_mm": None,
            "radial_doc_mm": None,
            "stepover_mm": None,
            "plunge_feed_mm_min": None,
            "ramp_feed_mm_min": None,
            "pre_ream_size_mm": None,
            "pre_ream_range_mm": None,
            "reaming_stock_mm": None,
            "tap_pitch_mm": None,
            "tap_drill_mm": None,
            "coolant": _coolant(p),
            "confidence": "medium",
            "notes": ["Development mock result — not a production recommendation."],
            "warnings": ["Mock mode is active; this result was not saved to the production cache."],
        }

        if family == "drill":
            depth = float(p.get("hole_depth_mm", 0.0) or 0.0)
            fpr = diameter * (0.006 if "hss" in tool_material.casefold() else 0.009)
            deep = depth > diameter * 4.0 if diameter else False
            if deep:
                fpr *= 0.75
            payload.update(
                feed_per_rev_mm=round(fpr, 4),
                feed_mm_min=round(rpm * fpr, 1),
                peck_mm=round(min(max(diameter * 1.5, 2.0), max(depth / 3.0, 2.0)), 2) if deep else None,
                peck_recommended=deep,
                recommended_cycle="G83 peck cycle" if deep else "G81 drilling cycle",
                notes=payload["notes"] + (["Hole depth is deep relative to diameter; use chip-clearing pecks."] if deep else []),
            )
        elif family == "reamer":
            depth = float(p.get("hole_depth_mm", 0.0) or 0.0)
            fpr = diameter * (0.025 if "carbide" in tool_material.casefold() else 0.018)
            stock = max(0.1, min(0.3, diameter * 0.02))
            pre = diameter - stock
            payload.update(
                feed_per_rev_mm=round(fpr, 4),
                feed_mm_min=round(rpm * fpr, 1),
                peck_mm=None,
                peck_recommended=False,
                recommended_cycle="Constant-feed reaming cycle; do not peck" if depth else "Constant-feed reaming cycle",
                pre_ream_size_mm=round(pre, 3),
                pre_ream_range_mm=f"{pre - 0.05:.3f}–{pre + 0.05:.3f} mm",
                reaming_stock_mm=round(stock, 3),
                notes=payload["notes"] + ["Feed the reamer continuously and avoid a drilling-style peck cycle."],
            )
        elif family == "tap":
            pitch = float(p.get("pitch_mm", 1.0) or 1.0)
            tap_drill = _metric_tap_drill(str(p.get("thread_size", "")), pitch)
            payload.update(
                feed_mm_min=round(rpm * pitch, 1),
                feed_per_rev_mm=round(pitch, 4),
                tap_pitch_mm=round(pitch, 4),
                tap_drill_mm=round(tap_drill, 3) if tap_drill else None,
                notes=payload["notes"] + ["Rigid-tap feed is derived from RPM × pitch."],
            )
        else:
            flutes = int(p.get("flute_count", p.get("insert_count", 2)) or 2)
            flutes = max(1, flutes)
            operation = request.operation.casefold()
            fpt_factor = 0.003 if "indexable" in request.tool_type.casefold() or family == "indexable" else 0.0045
            if operation == "slotting":
                fpt_factor *= 0.75
            if operation == "finishing":
                fpt_factor *= 0.6
            fpt = max(0.01, diameter * fpt_factor)
            axial = float(p.get("axial_doc_mm", 0.0) or 0.0)
            radial = float(p.get("radial_doc_mm", 0.0) or 0.0)
            if axial <= 0:
                axial = diameter * (0.5 if operation in {"roughing", "pocketing", "adaptive / dynamic milling"} else 0.2)
            if radial <= 0:
                radial = diameter if operation == "slotting" else diameter * 0.3
            payload.update(
                feed_per_tooth_mm=round(fpt, 4),
                feed_mm_min=round(rpm * flutes * fpt, 1),
                axial_doc_mm=round(axial, 3),
                radial_doc_mm=round(radial, 3),
                stepover_mm=round(radial, 3),
                plunge_feed_mm_min=round(rpm * flutes * fpt * 0.25, 1),
                ramp_feed_mm_min=round(rpm * flutes * fpt * 0.5, 1),
            )
            if family == "indexable":
                payload["notes"] = payload["notes"] + [
                    "Monitor chip thickness at the programmed radial engagement and adjust from the cut.",
                ]

        payload["cutting_speed_m_min"] = round(math.pi * diameter * rpm / 1000.0, 3)
        prompt = build_user_prompt(request, machine)
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return ServiceResponse(
            payload=payload,
            raw_text=raw,
            prompt=prompt,
            model=self.model,
            response_id="mock-development-result",
            usage={"mock": True},
            is_mock=True,
        )
