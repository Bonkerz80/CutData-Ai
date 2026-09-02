"""Prompt construction for the structured machining recommendation call."""

from __future__ import annotations

import json
from typing import Any

from ..config.constants import PROMPT_VERSION, SCHEMA_VERSION
from ..models.domain import MachiningRequest, MachineProfile
from ..models.schema import MACHINING_RESULT_SCHEMA
from ..services.normalization import normalize_request


SYSTEM_PROMPT = """You are an experienced CNC machining applications engineer advising a
working machine shop. Produce a sensible, conservative-but-productive starting
recommendation for the exact operation supplied by the user.

Rules:
- Work entirely in metric units. Never invent imperial units.
- Consider the material, hardness, tool material, coating, diameter, flute or
  insert count, axial and radial engagement, stickout, hole depth, machine
  limits, rigidity, and coolant.
- Reduce parameters when setup rigidity, hole depth, or stickout requires it.
- Distinguish roughing from finishing, slotting from side milling, drilling
  from reaming, HSS from carbide, and solid tools from indexable tools.
- Do not blindly use catalogue maximums. Give a realistic starting value that
  an experienced machinist can adjust on the machine.
- Return only the requested Structured Outputs object. Use null for fields that
  do not apply. Include short workshop notes and any important warnings.
- Basic arithmetic must be internally consistent: Vc = pi*D*RPM/1000;
  milling feed = RPM*teeth*feed_per_tooth; drilling/reaming feed =
  RPM*feed_per_rev; rigid tapping feed = RPM*pitch.
"""


def build_user_prompt(request: MachiningRequest, machine: MachineProfile) -> str:
    normalized = normalize_request(request)
    context: dict[str, Any] = {
        "request": normalized,
        "machine_profile": {
            "name": machine.name,
            "max_rpm": machine.max_rpm,
            "max_feed_mm_min": machine.max_feed_mm_min,
            "spindle_power_kw": machine.spindle_power_kw,
            "coolant_capability": machine.coolant_capability,
            "rigidity": machine.rigidity,
        },
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
    }
    return (
        "Calculate practical CNC speeds and feeds for this structured request. "
        "The result will be shown as a workshop calculator, so keep notes concise.\n\n"
        + json.dumps(context, ensure_ascii=False, sort_keys=True, indent=2)
    )


def schema_for_openai() -> dict[str, Any]:
    """Return a copy so callers cannot accidentally mutate the shared schema."""

    return json.loads(json.dumps(MACHINING_RESULT_SCHEMA))

