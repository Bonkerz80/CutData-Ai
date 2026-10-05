"""Central operation vocabulary and form behaviour for milling cutters.

The labels are deliberately workshop-facing.  They describe the machining
operation selected for the recommendation; they are not CAM toolpath names.
"""

from __future__ import annotations

from dataclasses import dataclass


ROUGHING_WATERLINE = "Roughing Waterline"
FACE_MILLING = "Face Milling"
FINISHING_WATERLINE = "Finishing Waterline"
FINISHING_PLANE = "Finishing Plane"
FLAT_LAND_FINISHING = "Flat Land Finishing"

ENCY_OPERATIONS = (
    ROUGHING_WATERLINE,
    FACE_MILLING,
    FINISHING_WATERLINE,
    FINISHING_PLANE,
    FLAT_LAND_FINISHING,
)

_BALL_NOSE_OPERATIONS = (
    ROUGHING_WATERLINE,
    FINISHING_WATERLINE,
    FINISHING_PLANE,
)
_BULL_NOSE_OPERATIONS = (
    ROUGHING_WATERLINE,
    FINISHING_WATERLINE,
    FINISHING_PLANE,
    FLAT_LAND_FINISHING,
)
_INDEXABLE_END_MILL_OPERATIONS = (
    ROUGHING_WATERLINE,
    FACE_MILLING,
    FLAT_LAND_FINISHING,
)

# Thread Mill is intentionally unchanged.  These values remain available for
# old requests and for the existing Thread Mill workflow.
LEGACY_MILLING_OPERATIONS = (
    "Slotting",
    "Profiling",
    "Pocketing",
    "Adaptive / Dynamic Milling",
    "Finishing",
    "Plunging",
    "Helical interpolation",
    "Ramp",
)


@dataclass(frozen=True)
class OperationFieldConfig:
    axial_label: str = "Axial DOC (mm)"
    radial_label: str = "Radial DOC / width (mm)"
    stock_label: str = "Stock remaining (mm, optional)"
    show_axial: bool = True
    show_radial: bool = True
    show_stock: bool = False
    show_pocket: bool = False
    show_material_thickness: bool = False
    show_finish_priority: bool = False


_GENERIC = OperationFieldConfig()
_LEGACY_CONFIG = {
    "slotting": OperationFieldConfig(show_stock=False),
    "profiling": OperationFieldConfig(show_stock=True),
    "pocketing": OperationFieldConfig(show_stock=True, show_pocket=True),
    "adaptive / dynamic milling": OperationFieldConfig(show_stock=True),
    "finishing": OperationFieldConfig(show_stock=True, show_finish_priority=True),
    "plunging": OperationFieldConfig(show_radial=False),
    "helical interpolation": OperationFieldConfig(show_stock=True, show_pocket=True),
    "ramp": OperationFieldConfig(show_radial=False),
}

_ENCY_CONFIG = {
    ROUGHING_WATERLINE.casefold(): OperationFieldConfig(
        axial_label="Depth step (mm)",
        radial_label="Radial engagement / stepover (mm)",
        stock_label="Stock remaining / stock to leave (mm, optional)",
        show_stock=True,
    ),
    FACE_MILLING.casefold(): OperationFieldConfig(
        axial_label="Depth of cut (mm)",
        radial_label="Step / width of cut (mm)",
    ),
    FINISHING_WATERLINE.casefold(): OperationFieldConfig(
        axial_label="Z step / finishing step (mm)",
        radial_label="Radial engagement / stepover (mm)",
        stock_label="Stock remaining (mm, optional)",
        show_radial=False,
        show_stock=True,
    ),
    FINISHING_PLANE.casefold(): OperationFieldConfig(
        axial_label="Axial step (mm)",
        radial_label="Stepover (mm)",
        stock_label="Stock remaining (mm, optional)",
        show_axial=False,
        show_stock=True,
    ),
    FLAT_LAND_FINISHING.casefold(): OperationFieldConfig(
        axial_label="Axial step (mm)",
        radial_label="Stepover (mm)",
        stock_label="Finishing stock / stock remaining (mm, optional)",
        show_axial=False,
        show_stock=True,
    ),
}


def operations_for_tool(tool_type: str) -> tuple[str, ...]:
    """Return the new-operation list for a tool, preserving Thread Mill."""

    value = str(tool_type or "").casefold()
    if value == "ball nose end mill":
        return _BALL_NOSE_OPERATIONS
    if value == "bull nose / corner radius end mill":
        return _BULL_NOSE_OPERATIONS
    if value == "face mill":
        return (FACE_MILLING,)
    if value in {"indexable end mill", "round insert / bull cutter"}:
        return _INDEXABLE_END_MILL_OPERATIONS
    if value == "thread mill":
        return LEGACY_MILLING_OPERATIONS
    if value == "end mill":
        return ENCY_OPERATIONS
    return ()


def default_operation_for_tool(tool_type: str) -> str:
    value = str(tool_type or "").casefold()
    if value == "ball nose end mill":
        return FINISHING_WATERLINE
    if value in {"bull nose / corner radius end mill", "end mill", "indexable end mill", "round insert / bull cutter"}:
        return ROUGHING_WATERLINE
    if value == "face mill":
        return FACE_MILLING
    if value == "thread mill":
        return LEGACY_MILLING_OPERATIONS[0]
    return ""


def operation_field_config(operation: str) -> OperationFieldConfig:
    value = str(operation or "").strip().casefold()
    return _ENCY_CONFIG.get(value, _LEGACY_CONFIG.get(value, _GENERIC))


def is_legacy_operation(operation: str) -> bool:
    value = str(operation or "").strip().casefold()
    return value in {item.casefold() for item in LEGACY_MILLING_OPERATIONS}


_LEGACY_OPERATION_TOOL_TYPES = frozenset({
    "end mill",
    "ball nose end mill",
    "bull nose / corner radius end mill",
    "face mill",
    "indexable end mill",
    "round insert / bull cutter",
})


def is_legacy_operation_for_tool(tool_type: str, operation: str) -> bool:
    """Return whether an operation is legacy for this tool identity.

    Thread Mill deliberately uses the historical labels as its current
    strategy vocabulary, so the same text is legacy only for the older
    generic/indexable milling workflows.
    """
    return (
        str(tool_type or "").strip().casefold() in _LEGACY_OPERATION_TOOL_TYPES
        and is_legacy_operation(operation)
    )


def legacy_operation_warning(tool_type: str, operation: str) -> str:
    if is_legacy_operation_for_tool(tool_type, operation):
        return (f"This saved calculation uses the legacy operation '{operation}'. "
                "Select a current ENCY operation before recalculating.")
    return ""


def active_parameters(tool_type: str, operation: str, parameters: dict) -> dict:
    """Filter machining inputs by meaning, independently of widget visibility."""
    result = dict(parameters)
    if str(operation or "").strip().casefold() == "ai guided":
        # Guided job geometry and optional constraints are intentionally not
        # filtered by the old operation-specific manual form rules.
        return result
    if operations_for_tool(tool_type):
        config = operation_field_config(operation)
        for key, applicable in {
            "axial_doc_mm": config.show_axial,
            "radial_doc_mm": config.show_radial,
            "stock_remaining_mm": config.show_stock,
            "pocket_depth_mm": config.show_pocket,
            "material_thickness_mm": config.show_material_thickness,
            "finish_priority": config.show_finish_priority,
            "ball_nose_mode": tool_type.casefold() == "ball nose end mill",
            "ball_nose_contact": tool_type.casefold() == "ball nose end mill",
            "surface_finish_priority": tool_type.casefold() == "ball nose end mill",
            "corner_radius_mm": tool_type.casefold() == "bull nose / corner radius end mill",
        }.items():
            if not applicable:
                result.pop(key, None)
    # Stock remaining is intentionally retained: zero can mean actual zero stock.
    optional_zero = {"existing_pilot_hole_diameter_mm", "corner_radius_mm",
                     "cutting_edge_length_mm", "flute_length_mm", "known_reaming_allowance_mm"}
    if tool_type.casefold() == "reamer":
        optional_zero.add("flute_count")
    if tool_type.casefold() == "tap":
        optional_zero.add("existing_hole_diameter_mm")
    return {key: value for key, value in result.items()
            if not (key in optional_zero and not isinstance(value, bool) and value == 0)}
