from pathlib import Path

from src.cutdata_ai.config.constants import (
    APP_NAME,
    BRAND_GRAPHITE,
    BRAND_RED,
    COMPANY_NAME,
    COMPANY_WEBSITE,
    ICON_ICO_PATH,
    ICON_PNG_PATH,
    ICON_SVG_PATH,
    PPT_FULL_LOGO_WHITE_PATH,
    PPT_HORIZONTAL_LOGO_PATH,
    PPT_LEGACY_ICON_PATH,
    PPT_SYMBOL_PATH,
    PUBLISHER_NAME,
    PRODUCT_DESCRIPTION,
    PRODUCT_TAGLINE,
    branding_asset,
)


def test_ppt_branding_and_packaged_icon_assets_are_present():
    assert APP_NAME == "CutData AI"
    assert PUBLISHER_NAME == "PPT"
    assert COMPANY_NAME == "Precision Press Tools & Engineering Services Ltd"
    assert COMPANY_WEBSITE == "https://www.ppt-eng.co.uk/"
    assert BRAND_RED == "#CE1D1D"
    assert BRAND_GRAPHITE == "#1B2228"
    assert PRODUCT_TAGLINE == "AI-Assisted CNC Machining Calculator"
    assert PRODUCT_DESCRIPTION == "AI-Assisted CNC Speeds & Feeds Calculator"
    for path in (ICON_SVG_PATH, ICON_PNG_PATH, ICON_ICO_PATH):
        assert isinstance(path, Path)
        assert path.is_file()
    for path in (
        PPT_HORIZONTAL_LOGO_PATH,
        PPT_FULL_LOGO_WHITE_PATH,
        PPT_SYMBOL_PATH,
        PPT_LEGACY_ICON_PATH,
    ):
        assert isinstance(path, Path)
        assert path.is_file()
    assert branding_asset("ppt-horizontal-logo.png") == PPT_HORIZONTAL_LOGO_PATH
    svg = ICON_SVG_PATH.read_text(encoding="utf-8")
    assert "#CE1D1D" in svg
    assert ">PPT<" in svg
