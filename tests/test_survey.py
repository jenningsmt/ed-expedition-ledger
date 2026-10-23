"""
Unit tests for engine.survey (sector-surveyor CSV tracking), engine.regionmap,
and the parser / exporter hooks for sector mode.
"""
from __future__ import annotations

import csv
import io
import json

import pytest

from engine.exporter import export_for_config, sector_slug
from engine.legs     import LegManager
from engine.parser   import EventParser
from engine.regionmap import find_region
from engine.survey   import SurveyTracker, parse_system_name, replay_events, system_key

HEADER = ("system_name,edsm_status,direction,steps_from_edge,spansh_edge_number,"
          "family,subsector,mass_prefix,mass_code,boxel,number")
ROWS = [
    "Hypiae Aim AA-F c25-0,not_in_edsm,backward,1,1,Hypiae Aim AA-F,AA-F,c25,c,25,0",
    "Hypiae Aim NA-A d0-3,not_in_edsm,bracketed_gap,,,Hypiae Aim NA-A,NA-A,d0,d,0,3",
]
# A Hypiae Aim position the region map places in Elysian Shore, although the
# game reports The Formidine Rift there (Hypiae Aim NS-U f2-0).
BOUNDARY_POS = [-8405.65625, 106.0, -5150.90625]
HA_POS       = [-8000.0, 100.0, -5600.0]


# ── Helpers ────────────────────────────────────────────────────────────────────

@pytest.fixture
def csv_path(tmp_path):
    p = tmp_path / "hypiae_aim_unreported_systems.csv"
    p.write_bytes(("\n".join([HEADER, *ROWS]) + "\n").encode("utf-8-sig"))
    return p


@pytest.fixture
def survey(csv_path):
    s = SurveyTracker(csv_path, "Hypiae Aim", retry_seconds=3600)
    yield s
    s.close()


def jump(system, ts="2026-10-23T01:00:00Z", pos=None):
    return {"timestamp": ts, "event": "FSDJump", "StarSystem": system,
            "SystemAddress": 1, "StarPos": pos or HA_POS, "JumpDist": 10.0}


def star_scan(system, was_discovered, ts="2026-10-23T01:00:05Z", dist=0.0, body_id=0):
    return {"timestamp": ts, "event": "Scan", "ScanType": "AutoScan",
            "BodyName": f"{system} A", "BodyID": body_id, "StarSystem": system,
            "StarType": "M", "DistanceFromArrivalLS": dist,
            "WasDiscovered": was_discovered, "WasMapped": False}


def all_found(system, ts="2026-10-23T01:03:00Z"):
    return {"timestamp": ts, "event": "FSSAllBodiesFound", "SystemName": system,
            "SystemAddress": 1, "Count": 5}


def codex(system, region, ts="2026-10-23T01:00:06Z"):
    return {"timestamp": ts, "event": "CodexEntry", "Name_Localised": "M Type Star",
            "Region": "$Codex_RegionName_31;", "Region_Localised": region,
            "System": system, "SystemAddress": 1, "IsNewEntry": False}


def read_rows(path):
    text = path.read_bytes().decode("utf-8-sig")
    return {r["system_name"]: r for r in csv.DictReader(io.StringIO(text))}


# ── Name parsing / region map ──────────────────────────────────────────────────

def test_parse_full_and_short_names():
    assert parse_system_name("Hypiae Aim CB-F d11-10") == {
        "sector": "Hypiae Aim", "subsector": "CB-F", "mass_code": "d",
        "boxel": 11, "number": 10,
    }
    short = parse_system_name("Hypiae Aim NA-A d3")
    assert short["boxel"] == 0 and short["number"] == 3
    assert parse_system_name("Sol") is None


def test_system_key_treats_omitted_zero_boxel_as_equal():
    assert system_key("Hypiae Aim NA-A d3") == system_key("hypiae aim na-a d0-3")
    assert system_key("Hypiae Aim NA-A d3") != system_key("Hypiae Aim NA-A d1-3")


def test_find_region_sol_and_formidine_spelling():
    assert find_region(0, 0, 0) == (18, "Inner Orion Spur")
    # Map index 31 is spelled the way the game does.
    hits = {find_region(x, 0, -5150)[1] for x in range(-9500, -8000, 100)}
    assert "Formidine Rift" not in hits


# ── Candidate updates ──────────────────────────────────────────────────────────

def test_new_candidate_visited_discovered_and_completed(survey, csv_path):
    survey.on_event(jump("Hypiae Aim AA-F c25-0"), "AristonX")
    survey.on_event(star_scan("Hypiae Aim AA-F c25-0", False), "AristonX")
    survey.on_event(all_found("Hypiae Aim AA-F c25-0"), "AristonX")

    row = read_rows(csv_path)["Hypiae Aim AA-F c25-0"]
    assert row["discovered"] == "new"
    assert row["completed"] == "AristonX"
    assert row["visited_utc"] == "2026-10-23T01:00:00Z"
    assert row["completed_utc"] == "2026-10-23T01:03:00Z"
    assert row["region"] == find_region(*HA_POS)[1]


def test_pre_discovered_candidate(survey, csv_path):
    survey.on_event(jump("Hypiae Aim AA-F c25-0"), "DovakiinMJ")
    survey.on_event(star_scan("Hypiae Aim AA-F c25-0", True), "DovakiinMJ")
    assert read_rows(csv_path)["Hypiae Aim AA-F c25-0"]["discovered"] == "discovered"


def test_short_game_name_matches_full_csv_name(survey, csv_path):
    survey.on_event(jump("Hypiae Aim NA-A d3"), "AristonX")
    survey.on_event(star_scan("Hypiae Aim NA-A d3", False), "AristonX")
    survey.on_event(all_found("Hypiae Aim NA-A d3"), "AristonX")
    rows = read_rows(csv_path)
    assert "Hypiae Aim NA-A d3" not in rows
    assert rows["Hypiae Aim NA-A d0-3"]["completed"] == "AristonX"


def test_only_arrival_star_decides_discovery(survey, csv_path):
    """Secondary stars (DistanceFromArrivalLS > 0) don't count, even as BodyID 0."""
    survey.on_event(jump("Hypiae Aim AA-F c25-0"), "AristonX")
    survey.on_event(star_scan("Hypiae Aim AA-F c25-0", False, dist=1200.0, body_id=0), "AristonX")
    assert read_rows(csv_path)["Hypiae Aim AA-F c25-0"]["discovered"] == ""
    survey.on_event(star_scan("Hypiae Aim AA-F c25-0", True, body_id=1), "AristonX")
    assert read_rows(csv_path)["Hypiae Aim AA-F c25-0"]["discovered"] == "discovered"


def test_first_value_wins(survey, csv_path):
    name = "Hypiae Aim AA-F c25-0"
    survey.on_event(jump(name), "AristonX")
    survey.on_event(star_scan(name, False), "AristonX")
    survey.on_event(all_found(name), "AristonX")
    # Revisit after the data was sold, by the other commander.
    survey.on_event(jump(name, ts="2026-10-24T00:00:00Z"), "DovakiinMJ")
    survey.on_event(star_scan(name, True, ts="2026-10-24T00:00:05Z"), "DovakiinMJ")
    survey.on_event(all_found(name, ts="2026-10-24T00:03:00Z"), "DovakiinMJ")

    row = read_rows(csv_path)[name]
    assert row["discovered"] == "new"
    assert row["completed"] == "AristonX"
    assert row["visited_utc"] == "2026-10-23T01:00:00Z"


def test_codex_region_overrides_map_region(survey, csv_path):
    name = "Hypiae Aim AA-F c25-0"
    survey.on_event(jump(name, pos=BOUNDARY_POS), "AristonX")
    assert read_rows(csv_path)[name]["region"] == "Elysian Shore"
    survey.on_event(codex(name, "The Formidine Rift"), "AristonX")
    assert read_rows(csv_path)[name]["region"] == "The Formidine Rift"


# ── Serendipitous systems ──────────────────────────────────────────────────────

def test_undiscovered_unlisted_sector_system_is_appended(survey, csv_path):
    name = "Hypiae Aim ZI-B d4"
    survey.on_event(jump(name), "AristonX")
    survey.on_event(star_scan(name, False), "AristonX")
    survey.on_event(all_found(name), "AristonX")

    row = read_rows(csv_path)[name]
    assert row["direction"] == "serendipitous"
    assert row["edsm_status"] == "not_in_edsm"
    assert (row["family"], row["subsector"], row["mass_prefix"], row["mass_code"],
            row["boxel"], row["number"]) == ("Hypiae Aim ZI-B", "ZI-B", "d0", "d", "0", "4")
    assert row["steps_from_edge"] == ""
    assert row["discovered"] == "new"
    assert row["completed"] == "AristonX"
    assert row["visited_utc"] == "2026-10-23T01:00:00Z"


def test_discovered_unlisted_system_is_ignored(survey, csv_path):
    survey.on_event(jump("Hypiae Aim ZI-B d4"), "AristonX")
    survey.on_event(star_scan("Hypiae Aim ZI-B d4", True), "AristonX")
    survey.on_event(all_found("Hypiae Aim ZI-B d4"), "AristonX")
    assert not csv_path.with_name(csv_path.stem + ".orig.csv").exists()  # never written
    assert "Hypiae Aim ZI-B d4" not in read_rows(csv_path)


def test_undiscovered_system_outside_sector_is_ignored(survey, csv_path):
    survey.on_event(jump("Phoi Aescs OM-W e1-0"), "AristonX")
    survey.on_event(star_scan("Phoi Aescs OM-W e1-0", False), "AristonX")
    assert "Phoi Aescs OM-W e1-0" not in read_rows(csv_path)


# ── File handling ──────────────────────────────────────────────────────────────

def test_write_preserves_bom_newlines_and_appends_columns(survey, csv_path):
    survey.on_event(jump("Hypiae Aim AA-F c25-0"), "AristonX")
    raw = csv_path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    header = raw.decode("utf-8-sig").splitlines()[0]
    assert header == HEADER + ",discovered,completed,region,visited_utc,completed_utc"
    backup = csv_path.with_name(csv_path.stem + ".orig.csv")
    assert backup.read_bytes().decode("utf-8-sig").splitlines()[0] == HEADER


def test_locked_file_holds_changes_until_writable(csv_path, monkeypatch):
    import engine.survey as survey_mod
    messages: list[str] = []
    s = SurveyTracker(csv_path, "Hypiae Aim", on_write_blocked=messages.append,
                      retry_seconds=3600)
    real_replace = survey_mod.os.replace

    def locked(*a, **kw):
        raise PermissionError("in use")
    monkeypatch.setattr(survey_mod.os, "replace", locked)

    s.on_event(jump("Hypiae Aim AA-F c25-0"), "AristonX")
    s.on_event(star_scan("Hypiae Aim AA-F c25-0", False), "AristonX")
    assert len(messages) == 1                       # notified once per episode
    assert read_rows(csv_path)["Hypiae Aim AA-F c25-0"].get("discovered") is None
    assert not csv_path.with_name(csv_path.name + ".tmp").exists()

    monkeypatch.setattr(survey_mod.os, "replace", real_replace)
    assert s.flush()
    assert read_rows(csv_path)["Hypiae Aim AA-F c25-0"]["discovered"] == "new"
    s.close()


def test_reload_and_replay_are_idempotent(csv_path):
    events = [
        ("Commander", json.dumps({"event": "Commander", "Name": "DovakiinMJ"})),
        ("FSDJump",   json.dumps(jump("Hypiae Aim ZI-B d4"))),
        ("Scan",      json.dumps(star_scan("Hypiae Aim ZI-B d4", False))),
        ("FSSAllBodiesFound", json.dumps(all_found("Hypiae Aim ZI-B d4"))),
    ]
    replay_events(SurveyTracker(csv_path, "Hypiae Aim"), events)
    first = csv_path.read_bytes()
    replay_events(SurveyTracker(csv_path, "Hypiae Aim"), events)
    assert csv_path.read_bytes() == first
    row = read_rows(csv_path)["Hypiae Aim ZI-B d4"]
    assert row["completed"] == "DovakiinMJ"
    assert sum(r["direction"] == "serendipitous" for r in read_rows(csv_path).values()) == 1


def test_summary_counts(survey):
    survey.on_event(jump("Hypiae Aim AA-F c25-0"), "AristonX")
    survey.on_event(star_scan("Hypiae Aim AA-F c25-0", False), "AristonX")
    survey.on_event(all_found("Hypiae Aim AA-F c25-0"), "AristonX")
    survey.on_event(jump("Hypiae Aim ZI-B d4"), "AristonX")
    survey.on_event(star_scan("Hypiae Aim ZI-B d4", False), "AristonX")
    assert survey.summary() == {
        "candidates": 2, "serendipitous": 1, "visited": 2,
        "new": 2, "discovered": 0, "completed": 1,
    }


# ── Parser integration ─────────────────────────────────────────────────────────

@pytest.fixture
def sector_cfg(cfg, tmp_path):
    c = dict(cfg)
    c.update(commanders=["AristonX", "DovakiinMJ"], mode="sector", sector="Hypiae Aim",
             waypoints=[], waypoint_map={}, expedition_end_system="",
             expedition_end_system_norm="", output_dir=tmp_path / "out", rarity={})
    c["output_dir"].mkdir()
    return c


def _line(ev: dict) -> str:
    return json.dumps(ev)


def test_parser_feeds_survey_with_session_commander(db, sector_cfg, survey, csv_path):
    legs = LegManager(db, sector_cfg)
    legs.ensure_first_leg()
    p = EventParser(db, legs, sector_cfg, survey=survey)
    p.process_line(_line({"timestamp": "2026-10-23T00:59:00Z", "event": "Commander",
                          "FID": "F9864061", "Name": "DovakiinMJ"}))
    p.process_line(_line(jump("Hypiae Aim AA-F c25-0")))
    p.process_line(_line(star_scan("Hypiae Aim AA-F c25-0", False)))
    p.process_line(_line(all_found("Hypiae Aim AA-F c25-0")))

    assert read_rows(csv_path)["Hypiae Aim AA-F c25-0"]["completed"] == "DovakiinMJ"
    assert db.get_active_leg()["name"] == "Hypiae Aim"
    with db._lock:
        assert db._exec("SELECT commander FROM systems").fetchone()[0] == "DovakiinMJ"
        assert db._exec("SELECT commander FROM bodies").fetchone()[0] == "DovakiinMJ"


def test_parser_gates_unlisted_commander(db, sector_cfg, survey, csv_path):
    legs = LegManager(db, sector_cfg)
    legs.ensure_first_leg()
    p = EventParser(db, legs, sector_cfg, survey=survey)
    p.process_line(_line({"timestamp": "2026-10-23T00:59:00Z", "event": "Commander",
                          "FID": "F13573114", "Name": "ALT FLOYD"}))
    p.process_line(_line(jump("Hypiae Aim AA-F c25-0")))
    assert read_rows(csv_path)["Hypiae Aim AA-F c25-0"].get("visited_utc") is None
    with db._lock:
        assert db._exec("SELECT COUNT(*) FROM jumps").fetchone()[0] == 0


def test_restore_state_recovers_session_commander(db, sector_cfg, survey, csv_path):
    legs = LegManager(db, sector_cfg)
    legs.ensure_first_leg()
    p1 = EventParser(db, legs, sector_cfg)
    p1.process_line(_line({"timestamp": "2026-10-23T00:59:00Z", "event": "Commander",
                           "FID": "F2584029", "Name": "AristonX"}))
    # Restart mid-journal: the new parser never sees the Commander line.
    p2 = EventParser(db, legs, sector_cfg, survey=survey)
    p2.restore_state()
    p2.process_line(_line(jump("Hypiae Aim AA-F c25-0")))
    p2.process_line(_line(star_scan("Hypiae Aim AA-F c25-0", False)))
    p2.process_line(_line(all_found("Hypiae Aim AA-F c25-0")))
    assert read_rows(csv_path)["Hypiae Aim AA-F c25-0"]["completed"] == "AristonX"


def test_shutdown_callback_only_when_live(db, sector_cfg):
    calls: list[int] = []
    legs = LegManager(db, sector_cfg)
    legs.ensure_first_leg()
    p = EventParser(db, legs, sector_cfg, on_session_end=lambda: calls.append(1))
    p.process_line(_line({"timestamp": "2026-10-23T02:00:00Z", "event": "Shutdown"}))
    assert calls == []
    p.live = True
    p.process_line(_line({"timestamp": "2026-10-23T03:00:00Z", "event": "Shutdown"}))
    assert calls == [1]


# ── Sector-mode export naming ──────────────────────────────────────────────────

def test_sector_slug():
    assert sector_slug("Hypiae Aim", "2026-10-23") == "sector_hypiae_aim_2026-10-23"


def test_export_for_config_uses_sector_names(db, sector_cfg):
    from datetime import datetime, timezone
    legs = LegManager(db, sector_cfg)
    legs.ensure_first_leg()
    xlsx = export_for_config(sector_cfg, db, db.get_active_leg()["leg_id"])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert xlsx.name == f"sector_hypiae_aim_{today}.xlsx"
    out = sector_cfg["output_dir"]
    assert (out / f"sector_hypiae_aim_{today}_bodies.csv").exists()
    assert (out / "master_rollup.xlsx").exists()
    header = (out / f"sector_hypiae_aim_{today}_systems.csv").read_text().splitlines()[0]
    assert header.endswith(",Commander")
