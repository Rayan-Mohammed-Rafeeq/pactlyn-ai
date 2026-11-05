from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from pactlyn.app.bootstrap import build_container
from pactlyn.ui.main_window import PactlynWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Pactlyn")
    app.setOrganizationName("Pactlyn")
    try:
        window = PactlynWindow(build_container())
    except Exception as exc:
        QMessageBox.critical(None, "Pactlyn could not start", str(exc))
        return 1
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    try:
        return app.exec()
    finally:
        # aboutToQuit normally performs cleanup, but app.exec() can also
        # return without emitting it (for example when startup or a Qt
        # callback exits early). shutdown() is idempotent.
        window.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
