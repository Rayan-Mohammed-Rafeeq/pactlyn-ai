from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtWidgets import QApplication

from pactlyn.app.bootstrap import build_container
from pactlyn.app.configuration import Settings
from pactlyn.ui.main_window import CaptureWorker, PactlynWindow


def main() -> None:
    with TemporaryDirectory(prefix="pactlyn-ui-capture-") as directory:
        settings = Settings(data_dir=Path(directory))
        container = build_container(settings)
        app = QApplication.instance() or QApplication(sys.argv)
        window = PactlynWindow(container)
        window.hide()
        result: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "model": settings.ollama_model,
            "endpoint": settings.ollama_url,
            "input": "I'm waiting for Rahul to send the project proposal by Friday.",
        }
        started = time.perf_counter()
        worker = CaptureWorker(
            container,
            str(result["input"]),
            "UI capture validation context: no external context",
        )

        def finished(value: object) -> None:
            result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            result["capture_result"] = value.model_dump(mode="json") if hasattr(value, "model_dump") else str(value)
            app.quit()

        def failed(error: str) -> None:
            result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            result["error"] = error
            app.quit()

        worker.finished.connect(finished)
        worker.failed.connect(failed)
        worker.start()
        app.exec()
        if worker.isRunning():
            worker.wait()
        window.shutdown()
        container.vectors.close()
        destination = Path(__file__).parent / "reports" / "capture-ui.json"
        destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    main()
