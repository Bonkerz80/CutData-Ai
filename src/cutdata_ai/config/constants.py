"""Stable application-wide configuration values.

The product name lives here so branding can be changed without searching the
UI and service code.
"""

import re

from .branding import (
    APP_NAME,
    ASSET_DIR,
    BRAND_GRAPHITE,
    BRAND_INK,
    BRAND_RED,
    COMPANY_NAME,
    COMPANY_WEBSITE,
    ICON_ICO_PATH,
    ICON_PNG_PATH,
    ICON_SVG_PATH,
    PPT_ASSET_DIR,
    PPT_FULL_LOGO_WHITE_PATH,
    PPT_HORIZONTAL_LOGO_PATH,
    PPT_LEGACY_ICON_PATH,
    PPT_SYMBOL_PATH,
    PRODUCT_DESCRIPTION,
    PRODUCT_TAGLINE,
    PUBLISHER_NAME,
    REPOSITORY_URL,
    WINDOWS_ICON_PATH,
    branding_asset,
    resource_path,
)


APP_VERSION = "0.2.8"
PROMPT_VERSION = "2026-09-28.1"
SCHEMA_VERSION = "3"
DEFAULT_MODEL = "gpt-6.1-sol"
DEFAULT_REASONING_EFFORT = "medium"

MODEL_DISPLAY_NAMES = {
    "gpt-6.1-sol": "GPT-6.1 Sol",
    "gpt-6-luna": "GPT-6 Luna",
    "gpt-6-sol": "GPT-6 Sol",
    "gpt-6-astra": "GPT-6 Astra",
}

# Used only when rendering historical records created by earlier releases.
HISTORICAL_MODEL_DISPLAY_NAMES = {
    "gpt-5.6-luna": "GPT-5.6 Luna",
    "gpt-5.6-terra": "GPT-5.6 Terra",
    "gpt-5.6-sol": "GPT-5.6 Sol",
}

SUPPORTED_MODELS = (
    "gpt-6.1-sol",
    "gpt-6-luna",
    "gpt-6-sol",
    "gpt-6-astra",
)

MODEL_DESCRIPTIONS = {
    "gpt-6.1-sol": "Default engine for careful tool research and machining advice.",
    "gpt-6-luna": "Efficient for focused, high-volume work.",
    "gpt-6-sol": "Higher-capability reasoning for demanding work.",
    "gpt-6-astra": "Highest-capability model for the hardest work.",
}

LEGACY_MODEL_MIGRATIONS = {
    "gpt-5.6-luna": "gpt-6-luna",
    "gpt-5.6-terra": "gpt-6-sol",
    "gpt-5.6-sol": "gpt-6-astra",
}

SUPPORTED_REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max")
REASONING_EFFORT_DISPLAY_NAMES = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra High",
    "max": "Maximum",
}

MACHINE_PROFILES = (
    {
        "name": "Generic CNC Mill",
        "max_rpm": 12000.0,
        "max_feed_mm_min": 10000.0,
        "spindle_power_kw": None,
        "coolant_capability": "Flood coolant",
        "rigidity": "medium",
    },
    {
        "name": "HAAS VF-9",
        "max_rpm": 10000.0,
        "max_feed_mm_min": 12000.0,
        "spindle_power_kw": None,
        "coolant_capability": "Flood coolant; internal coolant configurable",
        "rigidity": "high",
    },
    {
        "name": "HAAS VF-2",
        "max_rpm": 8000.0,
        "max_feed_mm_min": 10000.0,
        "spindle_power_kw": None,
        "coolant_capability": "Flood coolant; internal coolant configurable",
        "rigidity": "medium-high",
    },
    {
        "name": "Custom Machine",
        "max_rpm": 18000.0,
        "max_feed_mm_min": 12000.0,
        "spindle_power_kw": None,
        "coolant_capability": "Specify at machine",
        "rigidity": "medium",
    },
)

MATERIAL_GROUPS = {
    "STEELS": (
        "Mild Steel",
        "EN1A",
        "EN3",
        "EN8",
        "EN16",
        "EN19",
        "EN24",
        "EN32",
    ),
    "TOOL STEELS": (
        "D2 Annealed / Soft",
        "D2 Hardened",
        "P20",
        "H13",
        "Toolox 33",
        "Toolox 44",
    ),
    "STAINLESS": (
        "303 Stainless",
        "304 Stainless",
        "316 Stainless",
        "17-4PH",
    ),
    "NON-FERROUS": (
        "Aluminium 6082",
        "Aluminium 6061",
        "Aluminium 7075",
        "Brass",
        "Bronze",
        "Copper",
    ),
    "OTHER": (
        "Cast Iron",
        "Custom / Other",
    ),
}

MATERIALS = tuple(material for group in MATERIAL_GROUPS.values() for material in group)

TOOL_TYPES = (
    "Drill",
    "End Mill",
    "Ball Nose End Mill",
    "Bull Nose / Corner Radius End Mill",
    "Face Mill",
    "Indexable End Mill",
    "Round Insert / Bull Cutter",
    "Reamer",
    "Tap",
    "Thread Mill",
    "Countersink",
    "Chamfer Mill",
    "Spot Drill / Centre Drill",
)

TOOL_FAMILY_BY_TYPE = {
    "Drill": "drill",
    "Spot Drill / Centre Drill": "drill",
    "Countersink": "drill",
    "Chamfer Mill": "end_mill",
    "Chamfer Tool": "end_mill",
    "Reamer": "reamer",
    "Tap": "tap",
    "End Mill": "end_mill",
    "Ball Nose End Mill": "end_mill",
    "Bull Nose / Corner Radius End Mill": "end_mill",
    "Thread Mill": "end_mill",
    "Face Mill": "indexable",
    "Indexable End Mill": "indexable",
    "Round Insert / Bull Cutter": "indexable",
}

# These labels are retained only for reading older calculator state and
# recent-calculation rows.  They are deliberately absent from TOOL_TYPES so
# they cannot be selected for new calculations.
LEGACY_TOOL_FAMILY_BY_TYPE = {
    "Slot Cutter": "indexable",
    "T-Slot Cutter": "indexable",
}

DRILL_TOOL_MATERIALS = ("HSS", "HSS-Co / Cobalt", "Carbide", "Indexable")
MILL_TOOL_MATERIALS = ("Carbide", "HSS", "HSS-Co / Cobalt")
HOLE_TOOL_MATERIALS = ("HSS", "HSS-Co / Cobalt", "Carbide")
# ISO metric coarse pitches by nominal diameter (mm).
METRIC_COARSE_PITCH_MM = {
    1.6: 0.35, 2: 0.4, 2.5: 0.45, 3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25,
    10: 1.5, 12: 1.75, 14: 2.0, 16: 2.0, 18: 2.5, 20: 2.5, 22: 2.5, 24: 3.0,
    27: 3.0, 30: 3.5, 33: 3.5, 36: 4.0,
}
_METRIC_THREAD = re.compile(
    r"(?<![A-Za-z0-9])M\s*(\d+(?:\.\d+)?)(?:\s*[xX×*]\s*(\d+(?:\.\d+)?))?(?![\d.])",
    re.IGNORECASE,
)
COATINGS = (
    "Uncoated",
    "TiN",
    "TiCN",
    "TiAlN",
    "AlTiN",
    "Cupro (ITC)",
    "AlCrN",
    "ZrN",
    "DLC",
    "CVD Diamond",
    "Other / Proprietary",
)
COOLANTS = ("Flood coolant", "Through-tool coolant", "Mist", "Air blast", "None / dry")


def tool_family(tool_type: str) -> str:
    """Return the service/UI family for a tool label."""

    value = str(tool_type or "").strip().casefold()
    for mapping in (TOOL_FAMILY_BY_TYPE, LEGACY_TOOL_FAMILY_BY_TYPE):
        for label, family in mapping.items():
            if label.casefold() == value:
                return family
    return "end_mill"


def tool_materials_for(tool_type: str) -> tuple[str, ...]:
    """Tool materials offered for a tool label; empty when the insert decides."""

    family = tool_family(tool_type)
    if family == "indexable":
        return ()
    if family == "drill":
        return DRILL_TOOL_MATERIALS
    if family in {"reamer", "tap"}:
        return HOLE_TOOL_MATERIALS
    return MILL_TOOL_MATERIALS


def metric_thread_from_text(text: object) -> tuple[str, float | None] | None:
    """Read 'M10' or 'M10x1.25' out of free text as (size label, pitch)."""

    match = _METRIC_THREAD.search(str(text or ""))
    if not match:
        return None
    nominal = float(match.group(1))
    if not 1.0 <= nominal <= 100.0:
        return None
    pitch = float(match.group(2)) if match.group(2) else None
    if pitch is not None and not 0.0 < pitch < nominal:
        pitch = None
    return f"M{nominal:g}", pitch


def metric_thread_for_tool(snapshot: dict) -> tuple[str, float | None]:
    """Best known thread size and pitch for a library tap or thread mill.

    Recorded library values win, then a size written in the tool's name or
    code, then the nominal diameter. A missing pitch falls back to the
    standard coarse pitch.
    """

    size = str(snapshot.get("thread_size") or "").strip()
    try:
        pitch = float(snapshot.get("thread_pitch_mm") or 0) or None
    except (TypeError, ValueError):
        pitch = None
    parsed = metric_thread_from_text(size) if size else None
    if not size:
        for key in ("display_name", "model_code", "product_family"):
            parsed = metric_thread_from_text(snapshot.get(key))
            if parsed:
                break
        if parsed is None:
            try:
                diameter = float(snapshot.get("diameter_mm") or 0)
            except (TypeError, ValueError):
                diameter = 0.0
            if diameter in METRIC_COARSE_PITCH_MM:
                parsed = (f"M{diameter:g}", None)
        if parsed:
            size = parsed[0]
    if parsed and pitch is None:
        pitch = parsed[1] or METRIC_COARSE_PITCH_MM.get(float(parsed[0][1:]))
    return size, pitch


def compatible_tool_type(tool_type: str) -> str | None:
    """Map a stored label to an active UI label without changing stored data."""

    value = str(tool_type or "").strip().casefold()
    for label in TOOL_TYPES:
        if label.casefold() == value:
            return label
    for label, family in LEGACY_TOOL_FAMILY_BY_TYPE.items():
        if label.casefold() == value:
            return "Indexable End Mill" if family == "indexable" else None
    return None


def model_display_name(model: str) -> str:
    """Return a workshop-friendly model name without changing the API value."""

    return MODEL_DISPLAY_NAMES.get(model, HISTORICAL_MODEL_DISPLAY_NAMES.get(model, model))


def normalise_model_preference(model: object) -> str:
    """Migrate supported saved choices and safely default invalid preferences."""

    value = str(model or "").strip()
    if value in MODEL_DISPLAY_NAMES:
        return value
    return LEGACY_MODEL_MIGRATIONS.get(value, DEFAULT_MODEL)


def normalise_reasoning_effort(value: object) -> str:
    """Keep valid stored reasoning values and default unknown values safely."""

    effort = str(value or "").strip().casefold()
    return effort if effort in SUPPORTED_REASONING_EFFORTS else DEFAULT_REASONING_EFFORT
