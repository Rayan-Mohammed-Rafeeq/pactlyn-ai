# Linux setup

1. Install Python 3.11 or newer and `uv`. On minimal Debian/Ubuntu systems,
   install the Qt runtime libraries first:

   ```bash
   sudo apt install libgl1 libegl1 libxkbcommon0 libfontconfig1 libglib2.0-0 libdbus-1-3
   ```

2. Run `uv sync --extra dev` from the repository.
3. If you are upgrading an existing data directory, apply schema migrations with
   `uv run alembic upgrade head` (a fresh database is created automatically).
4. Start the application with `uv run pactlyn`.
5. Install and unlock a keyring such as GNOME Keyring or KWallet. Settings →
   Email stores the Resend API key there and refuses to save it in application
   data if the keyring is unavailable.
6. Install Ollama and pull a chat model plus `nomic-embed-text` if local AI is
   desired.

To install a user-scoped desktop launcher from a source checkout:

```bash
./packaging/linux/install-user.sh
```

For background reminders, keep Pactlyn running in the system tray. The current
shell supports tray notifications; desktop autostart packaging is planned for
the release packaging phase. Linux notification support depends on the
desktop environment's notification service.
