"""
Where the app keeps its files.

Run from the repo (python tracker.pyw): everything lives in the repo folder,
exactly as before — config.toml, tracker.db, output/, tracker.log.

Installed (PyInstaller build, EDLedger.exe): the install folder is replaced on
every upgrade, so user data lives outside it:

  %APPDATA%\\EDLedger\\config.toml            expedition config
  %LOCALAPPDATA%\\EDLedger\\                  tracker.db, tracker.log, baseline
  %LOCALAPPDATA%\\EDLedger\\output\\          exports
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "EDLedger"

FROZEN = bool(getattr(sys, "frozen", False))

# Repo root (source run) or the bundle's data folder (frozen).
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def _env_dir(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback) / APP_NAME


def config_dir() -> Path:
    return _env_dir("APPDATA", "AppData/Roaming") if FROZEN else ROOT


def data_dir() -> Path:
    return _env_dir("LOCALAPPDATA", "AppData/Local") if FROZEN else ROOT


def default_config_path() -> Path:
    return config_dir() / "config.toml"


def default_storage() -> dict[str, str]:
    """output_dir / db_path / baseline_path for a new config."""
    if not FROZEN:
        return {"output_dir": "output", "db_path": "tracker.db",
                "baseline_path": "validation_baseline.json"}
    d = data_dir()
    return {"output_dir": str(d / "output"), "db_path": str(d / "tracker.db"),
            "baseline_path": str(d / "validation_baseline.json")}


def default_journal_dir() -> str:
    return str(Path.home() / "Saved Games" / "Frontier Developments" / "Elite Dangerous")


def self_command(*args: str) -> list[str]:
    """Command line that re-runs this app with args (tray → config window)."""
    if FROZEN:
        return [sys.executable, *args]
    return [sys.executable, str(ROOT / "tracker.pyw"), *args]
