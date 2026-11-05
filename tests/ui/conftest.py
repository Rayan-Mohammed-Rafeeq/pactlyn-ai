from __future__ import annotations

import os
from collections.abc import Iterator

from pytest import fixture

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@fixture(scope="session")
def qapp() -> Iterator[object]:
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application
