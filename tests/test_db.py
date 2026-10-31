"""
Unit tests for engine.db's waypoint_systems filtering (waypoints_only_export).

Each test inserts data for two systems -- one "waypoint" the survey cares
about, one "transit" system merely passed through -- and asserts that
passing waypoint_systems restricts results to the waypoint system only,
while omitting it (None, the default) returns everything unfiltered.
"""
from __future__ import annotations

from engine.rarity import RuleMatch

WAYPOINT = "qiefoea hs-j d9-11"
TRANSIT  = "some transit system"


def _open_leg(db) -> int:
    return db.open_leg(1, None, "Start System", "2026-06-03T00:30:00Z")


def test_get_bodies_for_leg_filters_by_waypoint(db):
    leg_id = _open_leg(db)
    db.insert_body("2026-06-03T01:00:00Z", "Qiefoea HS-J d9-11", "Body A", 1,
                    "Water world", "", False, 100.0, True, True, leg_id)
    db.insert_body("2026-06-03T01:05:00Z", "Some Transit System", "Body B", 1,
                    "Icy body", "", False, 50.0, True, True, leg_id)

    unfiltered = db.get_bodies_for_leg(leg_id)
    assert len(unfiltered) == 2

    filtered = db.get_bodies_for_leg(leg_id, {WAYPOINT})
    assert len(filtered) == 1
    assert filtered[0]["system"] == "Qiefoea HS-J d9-11"


def test_get_systems_for_leg_filters_by_waypoint(db):
    leg_id = _open_leg(db)
    db.upsert_system("Qiefoea HS-J d9-11", 123, [0, 0, 0], "2026-06-03T01:00:00Z", leg_id)
    db.upsert_system("Some Transit System", 456, [1, 1, 1], "2026-06-03T01:05:00Z", leg_id)

    assert len(db.get_systems_for_leg(leg_id)) == 2
    filtered = db.get_systems_for_leg(leg_id, {WAYPOINT})
    assert len(filtered) == 1
    assert filtered[0]["system_name"] == "Qiefoea HS-J d9-11"


def test_get_organics_for_leg_filters_by_waypoint(db):
    leg_id = _open_leg(db)
    db.upsert_organic_scan("2026-06-03T01:00:00Z", "Qiefoea HS-J d9-11", 1,
                            "Bacterium", "Bacterium Alcyoneum", "Yellow", 3, leg_id)
    db.upsert_organic_scan("2026-06-03T01:05:00Z", "Some Transit System", 1,
                            "Fungoida", "Fungoida Setisis", "Red", 3, leg_id)

    assert len(db.get_organics_for_leg(leg_id)) == 2
    filtered = db.get_organics_for_leg(leg_id, {WAYPOINT})
    assert len(filtered) == 1
    assert filtered[0]["system"] == "Qiefoea HS-J d9-11"


def test_get_codex_for_leg_filters_by_waypoint(db):
    leg_id = _open_leg(db)
    db.insert_codex_entry("2026-06-03T01:00:00Z", "Codex A", "Region 1",
                           "Qiefoea HS-J d9-11", True, leg_id)
    db.insert_codex_entry("2026-06-03T01:05:00Z", "Codex B", "Region 1",
                           "Some Transit System", True, leg_id)

    assert len(db.get_codex_for_leg(leg_id)) == 2
    filtered = db.get_codex_for_leg(leg_id, {WAYPOINT})
    assert len(filtered) == 1
    assert filtered[0]["system"] == "Qiefoea HS-J d9-11"


def test_get_rare_finds_filters_by_waypoint(db):
    leg_id = _open_leg(db)
    match = RuleMatch(tag="very_small", details="radius 200km")
    db.upsert_rare_find("Qiefoea HS-J d9-11", 123, 1, "Body A", "Icy body",
                         leg_id, [match], was_discovered=0, was_mapped=0,
                         was_footfalled=0, distance_ls=100.0)
    db.upsert_rare_find("Some Transit System", 456, 1, "Body B", "Icy body",
                         leg_id, [match], was_discovered=0, was_mapped=0,
                         was_footfalled=0, distance_ls=50.0)

    assert len(db.get_rare_finds_for_leg(leg_id)) == 2
    filtered = db.get_rare_finds_for_leg(leg_id, {WAYPOINT})
    assert len(filtered) == 1
    assert filtered[0]["system"] == "Qiefoea HS-J d9-11"

    stats_all = db.get_rare_finds_stats(leg_id)
    assert stats_all["rare_finds_count"] == 2
    stats_filtered = db.get_rare_finds_stats(leg_id, {WAYPOINT})
    assert stats_filtered["rare_finds_count"] == 1


def test_get_body_class_breakdown_filters_by_waypoint(db):
    leg_id = _open_leg(db)
    db.insert_body("2026-06-03T01:00:00Z", "Qiefoea HS-J d9-11", "Body A", 1,
                    "Water world", "", False, 100.0, True, True, leg_id)
    db.insert_body("2026-06-03T01:05:00Z", "Some Transit System", "Body B", 1,
                    "Icy body", "", False, 50.0, True, True, leg_id)

    bkd_all = db.get_body_class_breakdown(leg_id)
    assert bkd_all == {"Water world": 1, "Icy body": 1}

    bkd_filtered = db.get_body_class_breakdown(leg_id, {WAYPOINT})
    assert bkd_filtered == {"Water world": 1}

    # None-leg (whole-expedition) variant, also filterable.
    bkd_grand_filtered = db.get_body_class_breakdown(None, {WAYPOINT})
    assert bkd_grand_filtered == {"Water world": 1}


def test_stats_for_leg_filters_system_scoped_metrics_only(db):
    leg_id = _open_leg(db)
    db.insert_body("2026-06-03T01:00:00Z", "Qiefoea HS-J d9-11", "Body A", 1,
                    "Water world", "", False, 100.0, was_discovered=False, was_mapped=True,
                    leg_id=leg_id)
    db.insert_body("2026-06-03T01:05:00Z", "Some Transit System", "Body B", 1,
                    "Icy body", "", False, 50.0, was_discovered=False, was_mapped=True,
                    leg_id=leg_id)
    db.insert_jump("2026-06-03T00:45:00Z", "Start System", "Some Transit System",
                    5.0, 1.0, [1, 1, 1], leg_id)
    db.insert_jump("2026-06-03T01:00:00Z", "Some Transit System", "Qiefoea HS-J d9-11",
                    3.0, 1.0, [2, 2, 2], leg_id)

    unfiltered = db.stats_for_leg(leg_id)
    assert unfiltered["bodies_scanned"] == 2
    assert unfiltered["first_discovered"] == 2
    assert unfiltered["systems_visited"] == 2
    # Travel stats are never filtered, even when waypoint_systems is passed below.
    assert unfiltered["commander_jumps"] == 2

    filtered = db.stats_for_leg(leg_id, {WAYPOINT})
    assert filtered["bodies_scanned"] == 1
    assert filtered["first_discovered"] == 1
    assert filtered["systems_visited"] == 1
    # Travel stats unchanged by filtering -- a jump isn't "in" one system.
    assert filtered["commander_jumps"] == 2
    assert filtered["distance_ly"] == unfiltered["distance_ly"]
