from pathlib import Path

from src.cutdata_ai.config.constants import (
    APP_NAME,
    COMPANY_NAME,
    COMPANY_WEBSITE,
    ICON_ICO_PATH,
    ICON_PNG_PATH,
    ICON_SVG_PATH,
    PUBLISHER_NAME,
)


def test_ppt_branding_and_packaged_icon_assets_are_present():
    assert APP_NAME == "CutData AI"
    assert PUBLISHER_NAME == "PPT"
    assert COMPANY_NAME == "Precision Press Tools & Engineering Services Ltd"
    assert COMPANY_WEBSITE == "https://www.ppt-eng.co.uk/"
    for path in (ICON_SVG_PATH, ICON_PNG_PATH, ICON_ICO_PATH):
        assert isinstance(path, Path)
        assert path.is_file()
    svg = ICON_SVG_PATH.read_text(encoding="utf-8")
    assert "#CE1D1D" in svg
    assert ">PPT<" in svg
