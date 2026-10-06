import json
import os

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog

from src.cutdata_ai.database.database import Database
from src.cutdata_ai.services.tool_import import ToolImportService
from src.cutdata_ai.services.tool_library import ToolLibraryService
from src.cutdata_ai.ui.tool_import_dialog import ToolImportDialog
from src.cutdata_ai.ui.tool_library_dialog import AddToolWizard, ToolLibraryDialog


class FakeResponses:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response):
        self.responses = FakeResponses(response)


def result_payload(entity="tool", **fields):
    return {
        "entity_type": entity,
        "display_name": "AI candidate name",
        "fields": fields,
        "provenance": [],
        "source_title": "Untrusted model title",
        "source_urls": [],
    }


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_manual_partial_and_pasted_text_are_review_candidates_only(tmp_path):
    response = {
        "output_text": json.dumps({
            **result_payload(manufacturer="WIDIA", model_code="EX-10", diameter_mm=10, coating=None),
            "provenance": [
                {"field": "manufacturer", "status": "user_supplied", "confidence": "high", "evidence": "WIDIA", "source_url": None},
                {"field": "model_code", "status": "user_supplied", "confidence": "high", "evidence": "EX-10", "source_url": None},
                {"field": "diameter_mm", "status": "user_supplied", "confidence": "high", "evidence": "10 mm", "source_url": None},
            ],
        }),
        "output": [],
    }
    client = FakeClient(response)
    service = ToolImportService(model="gpt-6-luna", client=client)
    manual = service.create_candidate(
        entity_type="tool", method="manual", manufacturer="WIDIA",
        input_text="WIDIA EX-10 10 mm carbide end mill",
    )
    assert manual.fields["manufacturer"] == "WIDIA"
    assert manual.field_provenance["manufacturer"]["status"] == "user_supplied"
    assert manual.field_provenance["coating"]["status"] == "unknown"
    assert manual.fields["coating"] is None
    assert manual.source_type == "manual"
    assert manual.source_text.endswith("carbide end mill")
    assert not client.responses.calls[0].get("tools")

    pasted = service.create_candidate(entity_type="tool", method="pasted", input_text="WIDIA EX-10 catalogue label")
    assert pasted.source_type == "pasted_text"
    assert pasted.source_text == "WIDIA EX-10 catalogue label"

    database = Database(tmp_path / "no-side-effects.sqlite3")
    assert database.recent(25) == []
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM cache_records").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM recent_calculations").fetchone()[0] == 0


def test_url_import_uses_manufacturer_domain_and_captures_verified_sources(tmp_path, qapp):
    official_url = "https://www.widia.com/en/products/insert-xdpt"
    response = {
        "output_text": json.dumps({
            **result_payload("insert", manufacturer="WIDIA", designation="XDPT170408PESRMM", grade="WP25PM"),
            "provenance": [
                {"field": "manufacturer", "status": "user_supplied", "confidence": "high", "evidence": "WIDIA", "source_url": None},
                {"field": "designation", "status": "source_confirmed", "confidence": "high", "evidence": "XDPT170408PESRMM", "source_url": official_url},
                {"field": "grade", "status": "source_confirmed", "confidence": "high", "evidence": "WP25PM", "source_url": official_url},
            ],
            "source_urls": [{"url": official_url, "title": "Ignored until citation is surfaced"}],
        }),
        "output": [{
            "type": "web_search_call",
            "action": {"type": "search", "sources": [{"type": "url", "url": official_url, "title": "Official WIDIA product page"}]},
        }],
    }
    client = FakeClient(response)
    candidate = ToolImportService(model="gpt-6-luna", client=client).create_candidate(
        entity_type="insert", method="url", manufacturer="WIDIA", source_url=official_url,
    )
    call = client.responses.calls[0]
    assert call["tools"] == [{"type": "web_search", "filters": {"allowed_domains": ["www.widia.com"]}}]
    assert candidate.field_provenance["grade"]["status"] == "source_confirmed"
    assert candidate.field_provenance["grade"]["source_url"] == official_url
    assert candidate.source_urls == [{"url": official_url, "title": "Official WIDIA product page"}]
    assert candidate.source_title == "Official WIDIA product page"
    assert candidate.source_retrieved_at
    assert candidate.source_type == "manufacturer_webpage"
    assert candidate.source_text == ""

    database = Database(tmp_path / "persist.sqlite3")
    initial_inserts = ToolLibraryService(database).list_inserts("XDPT170408PESRMM")
    preview_dialog = ToolImportDialog(lambda: None, "insert")
    preview_dialog._candidate_ready(candidate)
    row = preview_dialog._row_keys.index("grade")
    grade_status = preview_dialog.preview.cellWidget(row, 2)
    assert isinstance(grade_status, QComboBox)
    preview_dialog._save_candidate()
    assert preview_dialog.result() == QDialog.DialogCode.Accepted
    # Preview acceptance alone still does not write anything.
    assert ToolLibraryService(database).list_inserts("XDPT170408PESRMM") == initial_inserts
    values = ToolLibraryDialog._candidate_values(candidate, "insert")
    saved = ToolLibraryService(database).add_insert(values)
    persisted = ToolLibraryService(database).get_insert(saved["id"])
    assert persisted["source_url"] == official_url
    assert persisted["source_title"] == "Official WIDIA product page"
    assert persisted["source_retrieved_at"] == candidate.source_retrieved_at
    assert persisted["field_provenance"]["grade"]["status"] == "source_confirmed"
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM cache_records").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM recent_calculations").fetchone()[0] == 0


def test_unverified_claim_is_downgraded_and_preview_edits_become_user_supplied(qapp):
    fake_url = "https://www.widia.com/product"
    payload = {
        **result_payload("tool", manufacturer="WIDIA", diameter_mm=10),
        "provenance": [
            {"field": "diameter_mm", "status": "source_confirmed", "confidence": "high", "evidence": "10 mm", "source_url": fake_url},
        ],
    }
    response = {
        "output_text": json.dumps(payload),
        "output": [{"type": "web_search_call", "action": {"sources": [{"type": "url", "url": "https://www.example.com/not-widia"}]}}],
    }
    candidate = ToolImportService(client=FakeClient(response)).create_candidate(
        entity_type="tool", method="url", manufacturer="WIDIA", source_url=fake_url,
    )
    assert candidate.field_provenance["diameter_mm"]["status"] == "ai_inferred"

    dialog = ToolImportDialog(lambda: None, "tool", parent=qapp.activeWindow())
    dialog._candidate_ready(candidate)
    dialog.display_name.setText("Edited workshop cutter")
    row = dialog._row_keys.index("diameter_mm")
    dialog.preview.item(row, 1).setText("12")
    dialog._save_candidate()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert candidate.display_name == "Edited workshop cutter"
    assert candidate.fields["diameter_mm"] == 12
    assert candidate.field_provenance["diameter_mm"]["status"] == "user_supplied"


def test_enrichment_tolerates_list_type_in_response_metadata():
    response = {
        "output_text": json.dumps(result_payload(manufacturer="WIDIA", diameter_mm=25)),
        "output": [{"type": ["web_search_call"], "content": [{"type": ["output_text"], "text": "ignored"}]}],
    }
    candidate = ToolImportService(client=FakeClient(response)).create_candidate(
        entity_type="tool", method="manual", input_text="WIDIA 25 mm cutter",
        existing_record={"display_name": "My cutter", "iso_material_groups": ["P", "M"]},
    )
    assert candidate.display_name == "My cutter"
    assert candidate.fields["diameter_mm"] == 25
