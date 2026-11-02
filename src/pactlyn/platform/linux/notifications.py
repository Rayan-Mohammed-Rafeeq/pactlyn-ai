from __future__ import annotations

from collections.abc import Callable


class LinuxNotificationBackend:
    """Adapter boundary for desktop notifications.

    The system tray owns the current PySide6 delivery path. This callable
    backend keeps native notification integration replaceable for packaging.
    """

    def __init__(self, send: Callable[[str, str], None]):
        self.send = send

    def notify(self, title: str, body: str) -> None:
        self.send(title, body)
