# Linux setup

1. Install Python 3.11 or newer and `uv`. On minimal Debian/Ubuntu systems,
   install the Qt runtime libraries first:

   ```bash
   sudo apt install libgl1 libegl1 libxkbcommon0 libfontconfig1 libglib2.0-0 libdbus-1-3
   ```

2. Run `uv sync --extra dev` from the repository.
3. Start the application with `uv run pactlyn`.
4. Install Ollama and pull a chat model plus `nomic-embed-text` if local AI is
   desired.

For background reminders, keep Pactlyn running in the system tray. The current
shell supports tray notifications; desktop autostart packaging is planned for
the release packaging phase. Linux notification support depends on the
desktop environment's notification service.
