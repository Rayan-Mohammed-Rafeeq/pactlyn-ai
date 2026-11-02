from __future__ import annotations

import os
from pathlib import Path


class LinuxAutostart:
    """Manage a user-scoped desktop autostart entry without root privileges."""

    desktop_filename = "pactlyn.desktop"

    def __init__(self, *, executable: str = "pactlyn"):
        self.executable = executable

    @property
    def path(self) -> Path:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
        return config_home / "autostart" / self.desktop_filename

    def enable(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Pactlyn\n"
            "Comment=Remember what matters. Follow through.\n"
            f"Exec={self.executable}\n"
            "Icon=pactlyn\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
        self.path.chmod(0o600)
        return self.path

    def disable(self) -> None:
        self.path.unlink(missing_ok=True)

    def enabled(self) -> bool:
        return self.path.exists()
