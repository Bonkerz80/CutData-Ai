"""Small, serialisable domain objects for machining calculations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class MachineProfile:
    name: str
    max_rpm: float
    max_feed_mm_min: float
    spindle_power_kw: float | None = None
    coolant_capability: str = ""
    rigidity: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MachiningRequest:
    """All inputs needed for one calculation.

    The family-specific fields are intentionally kept in ``parameters``. This
    lets the application add tool families without changing the cache schema
    or the OpenAI request envelope.
    """

    machine: str
    material: str
    tool_type: str
    operation: str
    parameters: dict[str, Any] = field(default_factory=dict)
    custom_material: str = ""
    hardness_hrc: float | None = None
    unit_system: str = "metric"
    workflow_mode: str = "manual"
    tool_snapshot: dict[str, Any] = field(default_factory=dict)
    comparison_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        value = {
            "machine": self.machine,
            "material": self.material,
            "custom_material": self.custom_material,
            "hardness_hrc": self.hardness_hrc,
            "tool_type": self.tool_type,
            "operation": self.operation,
            "parameters": self.parameters,
            "unit_system": self.unit_system,
            "workflow_mode": self.workflow_mode,
            "tool_snapshot": self.tool_snapshot,
        }
        if self.comparison_history:
            value["comparison_history"] = self.comparison_history
        return value


@dataclass
class MachiningResult:
    """Structured values displayed by the workshop calculator."""

    rpm: float | None = None
    cutting_speed_m_min: float | None = None
    feed_mm_min: float | None = None
    feed_per_tooth_mm: float | None = None
    feed_per_rev_mm: float | None = None
    peck_mm: float | None = None
    peck_recommended: bool | None = None
    recommended_cycle: str | None = None
    axial_doc_mm: float | None = None
    radial_doc_mm: float | None = None
    stepover_mm: float | None = None
    plunge_feed_mm_min: float | None = None
    ramp_feed_mm_min: float | None = None
    pre_ream_size_mm: float | None = None
    pre_ream_range_mm: str | None = None
    reaming_stock_mm: float | None = None
    tap_pitch_mm: float | None = None
    tap_drill_mm: float | None = None
    estimated_spindle_power_kw: float | None = None
    estimated_spindle_torque_nm: float | None = None
    engagement_description: str | None = None
    setup_risk: str | None = None
    recommendation_summary: str | None = None
    recommended_operation: str | None = None
    recommended_strategy: str | None = None
    recommended_entry_method: str | None = None
    recommended_finish_allowance_mm: float | None = None
    recommended_pass_count: int | None = None
    pass_plan: list[dict[str, Any]] = field(default_factory=list)
    coolant: str = ""
    confidence: str = "medium"
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    research_status: str = "not_run"
    research_sources: list[dict[str, str]] = field(default_factory=list)
    verification_status: str = "not_run"
    verification_summary: str = ""
    verification_findings: list[str] = field(default_factory=list)
    history_comparison: list[str] = field(default_factory=list)
    verification_response_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def copy(self) -> "MachiningResult":
        return replace(
            self,
            notes=list(self.notes),
            warnings=list(self.warnings),
            pass_plan=[dict(stage) for stage in self.pass_plan],
            research_sources=[dict(source) for source in self.research_sources],
            verification_findings=list(self.verification_findings),
            history_comparison=list(self.history_comparison),
        )


@dataclass
class CalculationOutcome:
    """Calculation plus provenance/debug information for the UI."""

    result: MachiningResult
    normalized_request: dict[str, Any]
    request_hash: str
    source: str  # ai, cache, workshop, mock
    cache_hit: bool
    model: str
    prompt: str = ""
    raw_response: str = ""
    validated_response: str = ""
    response_id: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    validation_corrections: list[str] = field(default_factory=list)
    verification_prompt: str = ""
    verification_raw_response: str = ""
