"""Central PPT / CutData AI identity and packaged-resource lookup."""

from __future__ import annotations

import sys
from pathlib import Path


APP_NAME = "CutData AI"
PUBLISHER_NAME = "PPT"
COMPANY_NAME = "Precision Press Tools & Engineering Services Ltd"
COMPANY_WEBSITE = "https://www.ppt-eng.co.uk/"
BRAND_RED = "#CE1D1D"
BRAND_GRAPHITE = "#1B2228"
BRAND_INK = "#17212B"
PRODUCT_TAGLINE = "AI-Assisted CNC Machining Calculator"
PRODUCT_DESCRIPTION = "AI-Assisted CNC Speeds & Feeds Calculator"
REPOSITORY_URL = "https://github.com/Bonkerz80/CutData-Ai"


def resource_path(*parts: str) -> Path:
    """Return a resource path from source or the PyInstaller one-folder build."""

    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).joinpath("cutdata_ai", *parts)
    return Path(__file__).resolve().parent.parent.joinpath(*parts)


ASSET_DIR = resource_path("assets")
PPT_ASSET_DIR = ASSET_DIR / "ppt"
ICON_SVG_PATH = ASSET_DIR / "cutdata_ai.svg"
ICON_PNG_PATH = ASSET_DIR / "cutdata_ai.png"
ICON_ICO_PATH = ASSET_DIR / "cutdata_ai.ico"
PPT_HORIZONTAL_LOGO_PATH = PPT_ASSET_DIR / "ppt-horizontal-logo.png"
PPT_FULL_LOGO_WHITE_PATH = PPT_ASSET_DIR / "ppt-full-logo-white.png"
PPT_SYMBOL_PATH = PPT_ASSET_DIR / "ppt-symbol.png"
PPT_LEGACY_ICON_PATH = PPT_ASSET_DIR / "ppt-cutdata.ico"


def branding_asset(filename: str) -> Path:
    """Return an official PPT asset from source or a bundled application."""

    return PPT_ASSET_DIR / filename
