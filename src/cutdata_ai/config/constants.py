"""Stable application-wide configuration values.

The product name lives here so branding can be changed without searching the
UI and service code.
"""

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
    branding_asset,
    resource_path,
)


APP_VERSION = "0.1.5"
PROMPT_VERSION = "2026-09-03.2"
SCHEMA_VERSION = "2"
DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_REASONING_EFFORT = "medium"

MODEL_DISPLAY_NAMES = {
    "gpt-5.6-luna": "GPT-5.6 Luna",
    "gpt-5.6-terra": "GPT-5.6 Terra",
    "gpt-5.6-sol": "GPT-5.6 Sol",
}

SUPPORTED_MODELS = (
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
)

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
        "max_rpm": 12000.0,
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
    "Slot Cutter",
    "T-Slot Cutter",
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
    "Chamfer Mill": "drill",
    "Reamer": "reamer",
    "Tap": "tap",
    "End Mill": "end_mill",
    "Ball Nose End Mill": "end_mill",
    "Bull Nose / Corner Radius End Mill": "end_mill",
    "Thread Mill": "end_mill",
    "Face Mill": "indexable",
    "Indexable End Mill": "indexable",
    "Slot Cutter": "indexable",
    "T-Slot Cutter": "indexable",
}

DRILL_TOOL_MATERIALS = ("HSS", "HSS-Co / Cobalt", "Carbide", "Indexable")
MILL_TOOL_MATERIALS = ("Carbide", "HSS", "HSS-Co / Cobalt")
COATINGS = ("Uncoated", "TiN", "TiCN", "TiAlN", "AlTiN", "Other")
COOLANTS = ("Flood coolant", "Through-tool coolant", "Mist", "Air blast", "None / dry")


def tool_family(tool_type: str) -> str:
    """Return the service/UI family for a tool label."""

    return TOOL_FAMILY_BY_TYPE.get(tool_type, "end_mill")


def model_display_name(model: str) -> str:
    """Return a workshop-friendly model name without changing the API value."""

    return MODEL_DISPLAY_NAMES.get(model, model)
