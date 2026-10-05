"""Asynchronous AI import with an editable evidence/provenance review step."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..services.tool_import import ToolImportCandidate
from ..config.constants import DEFAULT_MODEL, model_display_name


_TOOL_FIELDS = (
    "manufacturer", "product_family", "model_code", "manufacturer_part_number",
    "tool_type", "diameter_mm", "effective_cutting_diameter_mm", "flute_count",
    "insert_count", "tool_material", "coating", "corner_radius_mm", "ball_radius_mm",
    "shank_diameter_mm", "cutting_edge_length_mm", "overall_length_mm",
    "approach_angle_deg", "holder_interface", "notes",
)
_INSERT_FIELDS = (
    "manufacturer", "product_family", "designation", "iso_designation", "ansi_designation",
    "manufacturer_part_number", "grade", "geometry", "chipbreaker", "shape", "insert_size",
    "inscribed_circle_mm", "thickness_mm", "corner_radius_mm", "cutting_edge_count",
    "coating", "substrate", "iso_material_groups", "manufacturer_application", "manufacturer_notes",
)
_NUMERIC_FIELDS = {
    "diameter_mm", "effective_cutting_diameter_mm", "flute_count", "insert_count",
    "corner_radius_mm", "ball_radius_mm", "shank_diameter_mm", "cutting_edge_length_mm",
    "overall_length_mm", "approach_angle_deg", "inscribed_circle_mm", "thickness_mm",
    "cutting_edge_count",
}
_INTEGER_FIELDS = {"flute_count", "insert_count", "cutting_edge_count"}
_STATUS_LABELS = {
    "user_supplied": "User supplied",
    "source_confirmed": "Source confirmed",
    "ai_inferred": "AI inferred — verify",
    "unknown": "Unknown",
}
_STATUS_COLORS = {
    "user_supplied": "#dff3e6", "source_confirmed": "#dbeafe",
    "ai_inferred": "#fff1cc", "unknown": "#eceff1",
}


class _ImportWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    done = Signal()

    def __init__(self, service_factory: Callable[[], Any], arguments: dict[str, Any]):
        super().__init__()
        self.service_factory = service_factory
        self.arguments = arguments

    @Slot()
    def run(self) -> None:
        try:
            candidate = self.service_factory().create_candidate(**self.arguments)
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit(candidate)
        finally:
            self.done.emit()


class ToolImportDialog(QDialog):
    def __init__(
        self,
        service_factory: Callable[[], Any],
        entity_type: str,
        *,
        existing_record: dict[str, Any] | None = None,
        known_fields: dict[str, Any] | None = None,
        model_name: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.service_factory = service_factory
        self.entity_type = entity_type
        self.existing_record = dict(existing_record or {})
        self.known_fields = dict(known_fields or {})
        self.candidate: ToolImportCandidate | None = None
        self._thread: QThread | None = None
        self._worker: _ImportWorker | None = None
        self._row_keys: list[str] = []
        self._original_values: dict[str, Any] = {}
        self.setWindowTitle("Enrich with AI" if existing_record else "Add with AI")
        self.resize(920, 730)
        root = QVBoxLayout(self)
        heading = QLabel("AI TOOL DATA IMPORT")
        heading.setObjectName("sectionTitle")
        root.addWidget(heading)
        model_label = QLabel(f"Using {model_name or model_display_name(DEFAULT_MODEL)} for this AI research")
        model_label.setObjectName("aiModelLabel")
        root.addWidget(model_label)
        hint = QLabel("The AI creates a candidate only. Review and edit every field before anything is saved to your library.")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        root.addWidget(hint)

        source_form = QFormLayout()
        self.method = QComboBox()
        self.method.addItem("Manual / partial data", "manual")
        self.method.addItem("Pasted box or catalogue text", "pasted")
        self.method.addItem("Manufacturer webpage URL", "url")
        self.method.addItem("Web search by product code", "search")
        source_form.addRow("Source", self.method)
        self.manufacturer = QLineEdit(str((existing_record or {}).get("manufacturer", "")))
        self.manufacturer.setPlaceholderText("Manufacturer name (helps prefer official sources)")
        source_form.addRow("Manufacturer", self.manufacturer)
        self.source_url = QLineEdit()
        self.source_url.setPlaceholderText("https://manufacturer.example/product-page")
        source_form.addRow("Manufacturer URL", self.source_url)
        self.input_text = QPlainTextEdit()
        self.input_text.setPlaceholderText("Product code, insert box wording, catalogue text, or a short description…")
        self.input_text.setMaximumHeight(100)
        self.input_text.setPlainText(self._existing_summary())
        source_form.addRow("Code / pasted information", self.input_text)
        root.addLayout(source_form)
        self.status = QLabel("Choose a source and build a candidate. Web search uses the Responses API; no machining values are generated here.")
        self.status.setWordWrap(True)
        self.status.setObjectName("hint")
        root.addWidget(self.status)

        preview_title = QLabel("REVIEW CANDIDATE — edit values or provenance before saving")
        preview_title.setObjectName("sectionTitle")
        root.addWidget(preview_title)
        self.display_name = QLineEdit()
        self.display_name.setPlaceholderText("Workshop display name")
        root.addWidget(self.display_name)
        self.preview = QTableWidget(0, 4)
        self.preview.setHorizontalHeaderLabels(["Field", "Value", "Evidence status", "Evidence / reason"])
        self.preview.setSelectionBehavior(QTableWidget.SelectRows)
        self.preview.setAlternatingRowColors(True)
        self.preview.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.preview, 1)
        self.sources = QPlainTextEdit()
        self.sources.setReadOnly(True)
        self.sources.setMaximumHeight(75)
        self.sources.setPlaceholderText("Manufacturer webpages or web-search sources will appear here when available.")
        root.addWidget(self.sources)

        controls = QHBoxLayout()
        self.build_button = QPushButton("Build AI candidate / research")
        self.build_button.clicked.connect(self._build_candidate)
        controls.addWidget(self.build_button)
        controls.addStretch(1)
        self.save_button = QPushButton("SAVE TO LIBRARY")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save_candidate)
        controls.addWidget(self.save_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        controls.addWidget(self.cancel_button)
        root.addLayout(controls)

    def _existing_summary(self) -> str:
        record = self.existing_record
        if not record:
            return ""
        return "\n".join(f"{key}: {record[key]}" for key in (
            "display_name", "model_code", "manufacturer_part_number", "designation", "grade", "coating"
        ) if record.get(key))

    def _build_candidate(self) -> None:
        if self._thread is not None:
            return
        args = {
            "entity_type": self.entity_type,
            "method": self.method.currentData(),
            "manufacturer": self.manufacturer.text().strip(),
            "input_text": self.input_text.toPlainText().strip(),
            "source_url": self.source_url.text().strip(),
            "known_fields": self.known_fields,
            "existing_record": self.existing_record,
        }
        self.build_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.status.setText("Researching and preparing a reviewable candidate…")
        self._thread = QThread(self)
        self._worker = _ImportWorker(self.service_factory, args)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._candidate_ready)
        self._worker.failed.connect(self._candidate_failed)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    def _thread_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self.build_button.setEnabled(True)

    def _candidate_failed(self, message: str) -> None:
        self.status.setText("The candidate could not be prepared. No library data was changed.")
        QMessageBox.warning(self, "AI tool import", message)

    def _candidate_ready(self, candidate: ToolImportCandidate) -> None:
        self.candidate = candidate
        self.display_name.setText(candidate.display_name)
        fields = _TOOL_FIELDS if self.entity_type == "tool" else _INSERT_FIELDS
        self._row_keys = list(fields)
        self._original_values = dict(candidate.fields)
        self.preview.setRowCount(len(self._row_keys))
        for row, key in enumerate(self._row_keys):
            label = QTableWidgetItem(key.replace("_", " ").title())
            label.setData(Qt.UserRole, key)
            label.setFlags(label.flags() & ~Qt.ItemIsEditable)
            self.preview.setItem(row, 0, label)
            value = candidate.fields.get(key)
            if isinstance(value, (list, tuple)):
                value = ", ".join(str(part) for part in value)
            cell = QTableWidgetItem("Unknown" if value in (None, "") else str(value))
            self.preview.setItem(row, 1, cell)
            provenance = candidate.field_provenance.get(key, {})
            status_combo = QComboBox()
            for code, text in _STATUS_LABELS.items():
                status_combo.addItem(text, code)
            current_status = provenance.get("status", "unknown")
            status_combo.setCurrentIndex(max(0, status_combo.findData(current_status)))
            status_combo.currentIndexChanged.connect(lambda _index, combo=status_combo: self._style_status(combo))
            self.preview.setCellWidget(row, 2, status_combo)
            evidence = QTableWidgetItem(str(provenance.get("evidence", "")))
            self.preview.setItem(row, 3, evidence)
            self._style_status(status_combo)
        self.preview.resizeColumnsToContents()
        self.preview.setColumnWidth(0, 165)
        self.preview.setColumnWidth(1, 185)
        self.preview.setColumnWidth(2, 220)
        if candidate.source_urls:
            self.sources.setPlainText("\n".join(
                f"{source.get('title') or 'Source'} — {source['url']}" for source in candidate.source_urls
            ))
        else:
            self.sources.setPlainText("No external source URL was returned for this candidate. Unverified values remain marked AI inferred or unknown.")
        self.status.setText(f"Candidate ready for review · record confidence {candidate.confidence.upper()} · nothing is saved until you choose SAVE TO LIBRARY.")
        self.save_button.setEnabled(True)

    def _style_status(self, combo: QComboBox) -> None:
        status = combo.currentData() or "unknown"
        combo.setStyleSheet(
            f"QComboBox {{ background-color: {_STATUS_COLORS.get(status, _STATUS_COLORS['unknown'])}; "
            "color: #17212B; font-weight: 600; }"
            "QComboBox QAbstractItemView { color: #17212B; background-color: #FFFFFF; }"
        )

    def _save_candidate(self) -> None:
        if self.candidate is None:
            return
        values: dict[str, Any] = {}
        provenance = dict(self.candidate.field_provenance)
        for row, key in enumerate(self._row_keys):
            item = self.preview.item(row, 1)
            raw = item.text().strip() if item else ""
            value: Any = None if not raw or raw.casefold() in {"unknown", "n/a", "not known"} else raw
            if value is not None and key in _NUMERIC_FIELDS:
                try:
                    numeric = float(value)
                    if numeric < 0 or (key in _INTEGER_FIELDS and not numeric.is_integer()):
                        raise ValueError
                    value = int(numeric) if key in _INTEGER_FIELDS else numeric
                except ValueError:
                    QMessageBox.warning(self, "Review candidate", f"Enter a valid non-negative number for {key.replace('_', ' ')}.")
                    return
            if value is not None and key == "iso_material_groups":
                value = [part.strip() for part in str(value).replace(";", ",").split(",") if part.strip()]
            status_combo = self.preview.cellWidget(row, 2)
            status = status_combo.currentData() if isinstance(status_combo, QComboBox) else "unknown"
            evidence = self.preview.item(row, 3).text().strip() if self.preview.item(row, 3) else ""
            original = self._original_values.get(key)
            if value != original:
                status = "user_supplied" if value is not None else "unknown"
                evidence = "Edited in the workshop review" if value is not None else ""
            if status == "source_confirmed" and (
                not self.candidate.source_urls or not evidence
            ):
                status = "ai_inferred"
            if value is None:
                status = "unknown"
            old = provenance.get(key, {})
            provenance[key] = {
                "status": status,
                "confidence": "high" if status == "user_supplied" else old.get("confidence", "low"),
                "evidence": evidence,
                "source_url": old.get("source_url", "") if status == "source_confirmed" else "",
            }
            values[key] = value
        display_name = self.display_name.text().strip()
        if not display_name:
            QMessageBox.warning(self, "Review candidate", "Enter a workshop name before saving.")
            return
        self.candidate.display_name = display_name
        self.candidate.fields.update(values)
        self.candidate.field_provenance = provenance
        self.accept()

    def closeEvent(self, event) -> None:
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(self, "Research is still running", "Wait for the candidate request to finish before closing this window.")
            event.ignore()
            return
        super().closeEvent(event)
