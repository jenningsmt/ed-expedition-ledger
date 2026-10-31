"""
Configuration loader.  Reads config.toml using stdlib tomllib (Python 3.11+)
and normalises values so the rest of the engine never touches raw config again.
"""
from __future__ import annotations

import os
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path


def _expand(path: str, root: Path) -> Path:
    """Expand %USERPROFILE% / ~ and resolve relative to the script root."""
    p = os.path.expandvars(os.path.expanduser(path))
    result = Path(p)
    if not result.is_absolute():
        result = root / result
    return result


def load(config_path: Path) -> dict:
    root = config_path.parent

    with open(config_path, "rb") as fh:
        raw = tomllib.load(fh)
    raw["config_path"] = Path(config_path).resolve()

    # ── Paths ──────────────────────────────────────────────────────────────────
    raw["journal_dir"] = _expand(raw["journal_dir"], root)
    raw["output_dir"]  = _expand(raw["output_dir"],  root)
    raw["db_path"]     = _expand(raw["db_path"],      root)
    raw["baseline_path"] = _expand(
        raw.get("baseline_path", "validation_baseline.json"), root
    )

    raw["output_dir"].mkdir(parents=True, exist_ok=True)

    # ── Commanders ─────────────────────────────────────────────────────────────
    # `commanders = [...]` tracks several CMDRs sharing one journal folder;
    # the older single `commander = '...'` key is still accepted.
    if "commanders" not in raw:
        raw["commanders"] = [raw["commander"]]
    raw.setdefault("commander", raw["commanders"][0])

    # ── Mode ───────────────────────────────────────────────────────────────────
    # "waypoints" (default): legs close at configured waypoints.
    # "sector": one open leg for a sector survey; exports are cumulative and
    # named sector_<sector>_<as-of date>.  Optional [survey] block points at a
    # sector-surveyor candidate CSV to keep up to date.
    raw.setdefault("mode", "waypoints")
    if raw["mode"] == "sector" and not raw.get("sector"):
        raise ValueError("mode = 'sector' requires a `sector` name in the config.")
    # Clustered candidate files (Sector Surveyor 1.6.0+) may also set:
    #   regions = ["R01", "R14"]           claimed survey regions (default: all)
    #   region_complete_when = "completed" | "visited"
    survey = raw.get("survey")
    if survey and survey.get("csv_path"):
        survey["csv_path"] = _expand(survey["csv_path"], root)
        when = survey.setdefault("region_complete_when", "completed")
        if when not in ("completed", "visited"):
            raise ValueError("[survey] region_complete_when must be 'completed' or 'visited'.")
        if "regions" in survey:
            survey["regions"] = [str(r).upper().strip() for r in survey["regions"]]

    # ── Timestamp cutoff ───────────────────────────────────────────────────────
    raw["expedition_start_dt"] = datetime.fromisoformat(
        raw["expedition_start_timestamp"].replace("Z", "+00:00")
    )

    # ── Normalised system names for fast matching ──────────────────────────────
    for wp in raw.get("waypoints", []):
        wp["system_norm"] = wp["system"].lower().strip()

    raw.setdefault("expedition_end_system", "")
    raw["expedition_end_system_norm"] = raw["expedition_end_system"].lower().strip()
    raw["expedition_start_system_norm"] = raw.get(
        "expedition_start_system", ""
    ).lower().strip()

    # Quick-lookup dict: normalised_system_name → waypoint label
    raw["waypoint_map"] = {
        wp["system_norm"]: wp["label"]
        for wp in raw.get("waypoints", [])
    }

    return raw
