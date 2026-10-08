"""The update box: tells the user a newer release exists and installs it."""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QProcess, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QTextBrowser, QVBoxLayout,
)

from ..config.constants import APP_NAME, APP_VERSION
from ..services.update_service import UpdateError, UpdateInfo, check_for_update, download_installer


class UpdateChecker(QObject):
    """Runs the release check off the UI thread and reports back by signal."""

    finished = Signal(object, str)  # (UpdateInfo | None, error text)

    def __init__(self, check: Callable[[], UpdateInfo | None] = check_for_update, parent=None):
        super().__init__(parent)
        self._check = check
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._run, name="update-check", daemon=True).start()

    def _run(self) -> None:
        info, error = None, ""
        try:
            info = self._check()
        except UpdateError as exc:
            error = str(exc)
        except Exception:  # a failed check must never disturb the calculator
            error = "The update check failed."
        self.running = False
        try:
            self.finished.emit(info, error)
        except RuntimeError:
            # The window closed while the check was still running.
            pass


class UpdateDialog(QDialog):
    """Offer a newer release: install it now, skip it, or decide later."""

    SKIP = 2
    _progress = Signal(int, int)
    _downloaded = Signal(str, str)  # (installer path, error text)

    def __init__(self, info: UpdateInfo, parent=None, *, download=download_installer,
                 launch: Callable[[str], bool] | None = None):
        super().__init__(parent)
        self.info = info
        self._download = download
        self._launch = launch or (lambda path: QProcess.startDetached(path, []))
        self._cancelled = False
        self._busy = False
        self.setWindowTitle(f"{APP_NAME} update")
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        heading = QLabel(f"{APP_NAME} {info.version} is available")
        heading.setObjectName("sectionTitle")
        root.addWidget(heading)
        current = QLabel(f"You have version {APP_VERSION}. Your settings, tool library and history are kept when you update.")
        current.setWordWrap(True)
        root.addWidget(current)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMarkdown(info.notes or "No release notes were published for this version.")
        self.notes.setMinimumHeight(220)
        root.addWidget(self.notes, 1)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        buttons = QHBoxLayout()
        self.install_button = QPushButton("DOWNLOAD AND INSTALL")
        self.install_button.setObjectName("primaryButton")
        self.install_button.setVisible(info.has_installer)
        self.install_button.clicked.connect(self._start_download)
        self.page_button = QPushButton("Open release page")
        self.page_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(info.page_url)))
        self.skip_button = QPushButton("Skip this version")
        self.skip_button.clicked.connect(lambda: self.done(self.SKIP))
        self.later_button = QPushButton("Later")
        self.later_button.clicked.connect(self.reject)
        buttons.addWidget(self.install_button)
        buttons.addWidget(self.page_button)
        buttons.addStretch(1)
        buttons.addWidget(self.skip_button)
        buttons.addWidget(self.later_button)
        root.addLayout(buttons)
        if not info.has_installer:
            self.status.setText("This release has no installer attached. Open the release page to download it.")
        self._progress.connect(self._show_progress)
        self._downloaded.connect(self._download_finished)

    def _start_download(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._cancelled = False
        self.install_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.later_button.setText("Cancel")
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.status.setText(f"Downloading {self.info.installer_name}…")
        threading.Thread(target=self._run_download, name="update-download", daemon=True).start()

    def _run_download(self) -> None:
        path, error = "", ""
        try:
            directory = Path(tempfile.gettempdir()) / "CutData AI updates"
            path = str(self._download(
                self.info, directory,
                progress=lambda done, total: self._progress.emit(done, total),
                cancelled=lambda: self._cancelled,
            ))
        except UpdateError as exc:
            error = str(exc)
        except Exception:
            error = "The download failed."
        try:
            self._downloaded.emit(path, error)
        except RuntimeError:
            pass

    def _show_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(min(100, int(done * 100 / total)))
            self.status.setText(f"Downloading {self.info.installer_name}… {done / 1048576:.0f} of {total / 1048576:.0f} MB")

    def _download_finished(self, path: str, error: str) -> None:
        self._busy = False
        self.progress.setVisible(False)
        self.later_button.setText("Later")
        self.install_button.setEnabled(True)
        self.skip_button.setEnabled(True)
        if error:
            self.status.setText(error)
            return
        if not self._launch(path):
            self.status.setText(f"The installer was downloaded to {path} but could not be started. Run it from there.")
            return
        # The installer replaces the program files, so the app has to close.
        self.accept()
        QApplication.quit()

    def reject(self) -> None:
        if self._busy:
            self._cancelled = True
            self.status.setText("Cancelling…")
            return
        super().reject()


def show_update_result(parent, info: UpdateInfo | None, error: str) -> None:
    """Tell the user the outcome of a check they asked for when there is no update."""

    if error:
        QMessageBox.warning(parent, f"{APP_NAME} update", error)
    elif info is None:
        QMessageBox.information(parent, f"{APP_NAME} update", f"You have the latest version ({APP_VERSION}).")
