# Linux launcher

After installing the Python package with `uv sync` or another supported
method, run `./packaging/linux/install-user.sh` from the repository. It adds a
user-scoped desktop launcher and icon under `~/.local/share`. No root access is
required. Remove those two files to uninstall the launcher; application data
under `~/.local/share/pactlyn` is separate and must be removed intentionally.
