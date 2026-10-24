"""
Tests for the config window's file writer (no window is opened) and the
installed-app paths in engine.paths.
"""
from __future__ import annotations

import importlib
from pathlib import Path

from engine.config import load
from tests.test_survey_clustered import write_clustered
from ui.config_window import _write_config


def _base(tmp_path, **kw) -> dict:
    data = {
        "journal_dir": str(tmp_path),
        "output_dir": str(tmp_path / "out"),
        "db_path": str(tmp_path / "tracker.db"),
        "baseline_path": str(tmp_path / "baseline.json"),
        "commanders": ["AristonX", "DovakiinMJ"],
        "mode": "waypoints",
        "sector": "",
        "expedition_start_timestamp": "2026-10-22T12:06:00Z",
        "expedition_start_system": "Pareco",
        "expedition_end_system": "HIP 58832",
        "waypoints": [{"label": "Waypoint 1", "system": "Lyed YJ-I d9-0"}],
        "survey": {"csv_path": "", "regions": [], "region_complete_when": "completed"},
    }
    data.update(kw)
    return data


def test_sector_config_round_trips_through_loader(tmp_path):
    csv_path = write_clustered(tmp_path / "r14.csv")
    cfg_path = tmp_path / "EDLedger" / "config.toml"   # parent created on save
    _write_config(cfg_path, _base(
        tmp_path, mode="sector", sector="Hypiae Aim",
        survey={"csv_path": str(csv_path), "regions": ["R02"],
                "region_complete_when": "visited"},
    ))
    cfg = load(cfg_path)
    assert cfg["mode"] == "sector" and cfg["sector"] == "Hypiae Aim"
    assert cfg["commanders"] == ["AristonX", "DovakiinMJ"]
    assert cfg["survey"]["csv_path"] == csv_path
    assert cfg["survey"]["regions"] == ["R02"]
    assert cfg["survey"]["region_complete_when"] == "visited"
    assert cfg["expedition_end_system"] == ""
    assert "waypoints" not in cfg
    assert cfg["db_path"] == tmp_path / "tracker.db"
    assert cfg["config_path"] == cfg_path.resolve()
    # New configs get the default rarity block.
    assert cfg["rarity"]["rule_jumponium"] is True
    assert "Carbon" in cfg["rarity"]["jumponium_materials"]


def test_waypoint_config_keeps_existing_rarity_and_options(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[rarity]\nhigh_gravity_g = 2.5\n", encoding="utf-8")
    _write_config(cfg_path, _base(tmp_path, waypoints_only_export=True))
    cfg = load(cfg_path)
    assert cfg["mode"] == "waypoints"
    assert cfg["waypoint_map"] == {"lyed yj-i d9-0": "Waypoint 1"}
    assert cfg["waypoints_only_export"] is True
    assert cfg["rarity"] == {"high_gravity_g": 2.5}
    assert "[survey]" not in cfg_path.read_text(encoding="utf-8")


def test_quotes_in_values_survive(tmp_path):
    cfg_path = tmp_path / "config.toml"
    _write_config(cfg_path, _base(tmp_path, expedition_end_system="Parrot's Head Sector EL-Y d70"))
    assert load(cfg_path)["expedition_end_system"] == "Parrot's Head Sector EL-Y d70"


def test_installed_paths_live_outside_the_install_folder(monkeypatch, tmp_path):
    from engine import paths
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setattr(paths, "FROZEN", True)
    assert paths.default_config_path() == tmp_path / "Roaming" / "EDLedger" / "config.toml"
    storage = paths.default_storage()
    assert Path(storage["output_dir"]) == tmp_path / "Local" / "EDLedger" / "output"
    assert Path(storage["db_path"]) == tmp_path / "Local" / "EDLedger" / "tracker.db"
    assert paths.self_command("--configure")[1:] == ["--configure"]


def test_source_run_paths_unchanged():
    from engine import paths
    importlib.reload(paths)
    assert not paths.FROZEN
    assert paths.default_config_path() == paths.ROOT / "config.toml"
    assert paths.default_storage()["output_dir"] == "output"
    assert paths.self_command("--configure")[1].endswith("tracker.pyw")
