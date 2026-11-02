from __future__ import annotations

from pactlyn.platform.linux.autostart import LinuxAutostart


def test_linux_autostart_is_user_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    autostart = LinuxAutostart(executable="/opt/pactlyn")
    path = autostart.enable()
    assert path == tmp_path / "config" / "autostart" / "pactlyn.desktop"
    assert autostart.enabled()
    assert "Exec=/opt/pactlyn" in path.read_text()
    autostart.disable()
    assert not autostart.enabled()
