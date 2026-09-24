"""Keep Qt test windows isolated so the full suite doesn't accumulate widgets."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent


@pytest.fixture(autouse=True)
def flush_deferred_qt_deletes():
    """Deliver queued ``deleteLater`` events after each test case."""

    yield
    app = QCoreApplication.instance()
    if app is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
