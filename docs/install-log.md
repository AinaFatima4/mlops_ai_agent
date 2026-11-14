# Install Log

All software installed on this machine for Assignment 3.

| Date | What | Command / Source | Where |
|---|---|---|---|
| 2026-11-14 | WSL2 + Ubuntu 24.04 | `wsl --install -d Ubuntu-24.04` | Windows |
| 2026-11-14 | Docker Engine + Compose plugin | apt, official Docker repository | WSL |
| 2026-11-14 | uv 0.13.8 | official installer → `/usr/local/bin` | WSL |
| 2026-11-14 | ruff, pytest (dev) | `uv add --dev` | project `.venv` |

Python packages: full list with exact versions in `pyproject.toml` and `uv.lock`.

Full removal: `wsl --unregister Ubuntu-24.04` (PowerShell).
