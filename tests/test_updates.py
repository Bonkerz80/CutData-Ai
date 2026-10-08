import hashlib
import io
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.cutdata_ai.config.constants import APP_VERSION, REPOSITORY_URL
from src.cutdata_ai.database.database import Database
from src.cutdata_ai.services.update_service import (
    LATEST_RELEASE_API, UpdateError, UpdateInfo, check_for_update, download_installer,
    is_newer, parse_version, release_from_payload,
)
from src.cutdata_ai.ui.dialogs import AboutDialog
from src.cutdata_ai.ui.main_window import MainWindow
from src.cutdata_ai.ui.update_dialog import UpdateChecker, UpdateDialog

DOWNLOAD = f"{REPOSITORY_URL}/releases/download/v9.0.0/CutData-AI-Setup-9.0.0.exe"
CONTENT = b"installer bytes" * 1000


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _payload(tag="v9.0.0", **extra):
    payload = {
        "tag_name": tag, "html_url": f"{REPOSITORY_URL}/releases/tag/{tag}", "body": "## Changes\n- Better",
        "draft": False, "prerelease": False,
        "assets": [
            {"name": "notes.txt", "browser_download_url": f"{REPOSITORY_URL}/releases/download/{tag}/notes.txt"},
            {"name": "CutData-AI-Setup-9.0.0.exe", "browser_download_url": DOWNLOAD, "size": len(CONTENT),
             "digest": "sha256:" + hashlib.sha256(CONTENT).hexdigest()},
        ],
    }
    payload.update(extra)
    return payload


def _info(**changes):
    values = dict(version="9.0.0", notes="## Changes", page_url=f"{REPOSITORY_URL}/releases/tag/v9.0.0",
                  installer_url=DOWNLOAD, installer_name="CutData-AI-Setup-9.0.0.exe",
                  installer_size=len(CONTENT), sha256=hashlib.sha256(CONTENT).hexdigest())
    values.update(changes)
    return UpdateInfo(**values)


def test_versions_compare_numerically():
    assert parse_version("v0.2.10") == (0, 2, 10)
    assert is_newer("0.2.10", "0.2.9") and is_newer("v1.0", "0.9.9")
    assert not is_newer("0.2.9", "0.2.9") and not is_newer("0.2", "0.2.0")
    assert not is_newer("0.2.8", "0.2.9") and not is_newer("nightly", "0.2.9")
    assert LATEST_RELEASE_API == "https://api.github.com/repos/Bonkerz80/CutData-Ai/releases/latest"


def test_release_is_read_and_only_this_projects_installer_is_accepted():
    info = release_from_payload(_payload())
    assert info == _info(notes="## Changes\n- Better")
    assert check_for_update("0.2.9", fetch=lambda url: _payload()) == info
    assert check_for_update("9.0.0", fetch=lambda url: _payload()) is None
    assert check_for_update("0.2.9", fetch=lambda url: None) is None
    assert release_from_payload(_payload(draft=True)) is None
    assert release_from_payload(_payload(prerelease=True)) is None

    # An installer hosted anywhere else, or oddly named, is never offered for download.
    elsewhere = _payload(assets=[{"name": "CutData-AI-Setup-9.0.0.exe", "browser_download_url": "https://example.com/CutData-AI-Setup-9.0.0.exe"}])
    assert not release_from_payload(elsewhere).has_installer
    renamed = _payload(assets=[{"name": "setup.exe", "browser_download_url": DOWNLOAD.replace("CutData-AI-Setup-9.0.0", "setup")}])
    assert not release_from_payload(renamed).has_installer
    foreign_page = release_from_payload(_payload(html_url="https://example.com/x"))
    assert foreign_page.page_url == f"{REPOSITORY_URL}/releases"


def test_download_checks_size_and_published_hash(tmp_path):
    seen = []
    path = download_installer(_info(), tmp_path, progress=lambda done, total: seen.append((done, total)),
                              opener=lambda url: io.BytesIO(CONTENT))
    assert path.name == "CutData-AI-Setup-9.0.0.exe" and path.read_bytes() == CONTENT
    assert seen[-1] == (len(CONTENT), len(CONTENT))

    for bad, message in ((CONTENT[:-5], "incomplete"), (CONTENT[:-1] + b"x", "did not match")):
        target = tmp_path / message
        with pytest.raises(UpdateError, match=message):
            download_installer(_info(), target, opener=lambda url, data=bad: io.BytesIO(data))
        assert list(target.iterdir()) == []

    with pytest.raises(UpdateError):
        download_installer(_info(installer_url="https://example.com/CutData-AI-Setup-9.0.0.exe"), tmp_path,
                           opener=lambda url: io.BytesIO(CONTENT))
    with pytest.raises(UpdateError, match="cancelled"):
        download_installer(_info(), tmp_path / "c", opener=lambda url: io.BytesIO(CONTENT), cancelled=lambda: True)


def _wait(qapp, condition, seconds=5.0):
    import time

    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert condition()


def test_checker_reports_result_and_never_raises(qapp):
    results = []
    checker = UpdateChecker(check=lambda: _info())
    checker.finished.connect(lambda info, error: results.append((info, error)))
    checker.start()
    _wait(qapp, lambda: results)
    assert results == [(_info(), "")]

    def broken():
        raise UpdateError("offline")

    results.clear()
    failing = UpdateChecker(check=broken)
    failing.finished.connect(lambda info, error: results.append((info, error)))
    failing.start()
    _wait(qapp, lambda: results)
    assert results == [(None, "offline")]


def test_update_box_downloads_then_starts_the_installer(qapp, tmp_path, monkeypatch):
    launched, quits = [], []
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: quits.append(True)))

    def fake_download(info, directory, progress=None, cancelled=None):
        progress(len(CONTENT), len(CONTENT))
        target = tmp_path / info.installer_name
        target.write_bytes(CONTENT)
        return target

    dialog = UpdateDialog(_info(), download=fake_download, launch=lambda path: launched.append(path) or True)
    dialog.show()
    assert "9.0.0 is available" in dialog.findChild(type(dialog.status), "sectionTitle").text()
    assert APP_VERSION in dialog.findChildren(type(dialog.status))[1].text()
    assert "Better" not in dialog.notes.toPlainText() and "Changes" in dialog.notes.toPlainText()
    assert dialog.install_button.isVisible()
    dialog.install_button.click()
    _wait(qapp, lambda: launched)
    assert launched == [str(tmp_path / "CutData-AI-Setup-9.0.0.exe")] and quits == [True]

    def failing(info, directory, progress=None, cancelled=None):
        raise UpdateError("The download failed. Check the internet connection and try again.")

    retry = UpdateDialog(_info(), download=failing, launch=lambda path: launched.append(path) or True)
    retry.show()
    retry.install_button.click()
    _wait(qapp, lambda: "download failed" in retry.status.text())
    assert retry.install_button.isEnabled() and len(launched) == 1

    manual = UpdateDialog(_info(installer_url="", installer_name=""))
    manual.show()
    assert not manual.install_button.isVisible() and "release page" in manual.status.text()
    for item in (dialog, retry, manual):
        item.close()


def test_main_window_checks_only_on_request_and_respects_skip(qapp, tmp_path, monkeypatch):
    shown = []

    class FakeDialog:
        SKIP = UpdateDialog.SKIP

        def __init__(self, info, parent=None):
            shown.append(info.version)

        def exec(self):
            return self.SKIP

    monkeypatch.setattr("src.cutdata_ai.ui.main_window.UpdateDialog", FakeDialog)
    messages = []
    monkeypatch.setattr("src.cutdata_ai.ui.main_window.show_update_result", lambda parent, info, error: messages.append((info, error)))
    window = MainWindow(Database(tmp_path / "updates.sqlite3"))
    try:
        # A source run or test never starts a check by itself.
        assert not window._update_checker.running
        assert window.auto_update_enabled()

        window._update_check_finished(_info(), "")
        assert shown == ["9.0.0"]
        assert window.settings_service.load_json_setting("update_skip_version", "") == "9.0.0"
        # The skipped version is not offered again at start-up, but is when asked for.
        window._update_check_finished(_info(), "")
        assert shown == ["9.0.0"]
        window._update_check_manual = True
        window._update_check_finished(_info(), "")
        assert shown == ["9.0.0", "9.0.0"]
        window._update_check_finished(_info(version="9.1.0"), "")
        assert shown[-1] == "9.1.0"

        # Start-up checks stay silent when there is nothing new or no connection.
        window._update_check_finished(None, "")
        window._update_check_finished(None, "offline")
        assert messages == []
        window._update_check_manual = True
        window._update_check_finished(None, "")
        assert messages == [(None, "")]

        about = AboutDialog(window)
        about.show()
        assert about.update_button.isVisible() and about.auto_update.isChecked()
        about.auto_update.setChecked(False)
        assert not window.auto_update_enabled()
        about.close()
        plain = AboutDialog()
        plain.show()
        assert not plain.update_button.isVisible()
        plain.close()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
