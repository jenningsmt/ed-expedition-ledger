"""
Sector survey tracker.

Keeps a sector-surveyor candidate CSV (one row per system believed to exist
but unreported to EDSM) up to date as the commander flies the sector:

  discovered     "new" if the arrival star's Scan says WasDiscovered=false,
                 else "discovered"
  completed      commander name, on FSSAllBodiesFound
  region         galactic region (CodexEntry Region_Localised when the game
                 reports one, else derived from StarPos via engine.regionmap)
  visited_utc    first arrival timestamp
  completed_utc  FSSAllBodiesFound timestamp

Undiscovered in-sector systems missing from the CSV are appended with
direction="serendipitous".  Discovered systems missing from the CSV are ignored.

Write rules
-----------
* First value wins: a non-empty cell is never overwritten, so replaying
  journals is idempotent and manual edits survive.  The one exception is
  region — the game's CodexEntry region replaces a map-derived one, because
  the map is ~49 ly per cell and misreads systems near region boundaries.
* The CSV is the persistent state.  It is rewritten atomically (temp file +
  os.replace) and keeps its BOM / line endings.  If the file is locked (open
  in Excel), changes stay in memory and the write is retried on a timer.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Callable

from .regionmap import find_region

log = logging.getLogger(__name__)

SURVEY_COLUMNS = ["discovered", "completed", "region", "visited_utc", "completed_utc"]

# Procedural name: "<Sector> AB-C d12-34".  The "12-" part is omitted by the
# game when it is 0 ("NA-A d3" == "NA-A d0-3").
_NAME_RE = re.compile(
    r"^(?P<sector>.+?) (?P<sub>[A-Z]{2}-[A-Z]) (?P<mc>[a-h])(?:(?P<n1>\d+)-)?(?P<n2>\d+)$",
    re.IGNORECASE,
)


def parse_system_name(name: str) -> "dict | None":
    """Split a procedurally generated system name into its parts, or None."""
    m = _NAME_RE.match(name.strip())
    if not m:
        return None
    return {
        "sector":    m["sector"],
        "subsector": m["sub"].upper(),
        "mass_code": m["mc"].lower(),
        "boxel":     int(m["n1"] or 0),
        "number":    int(m["n2"]),
    }


def system_key(name: str) -> str:
    """Normalised lookup key: lowercase, with the boxel number always explicit."""
    p = parse_system_name(name)
    if p is None:
        return name.lower().strip()
    return (f"{p['sector'].lower()} {p['subsector'].lower()} "
            f"{p['mass_code']}{p['boxel']}-{p['number']}")


class SurveyTracker:
    def __init__(
        self,
        csv_path: Path,
        sector: str,
        on_write_blocked: "Callable[[str], None] | None" = None,
        retry_seconds: float = 30.0,
    ) -> None:
        self.path = Path(csv_path)
        self._sector_prefix = sector.lower().strip() + " "
        self._on_write_blocked = on_write_blocked
        self._retry_seconds = retry_seconds

        # Set False during backfill/rebuild to batch writes; call flush() after.
        self.autoflush = True

        self._lock = threading.RLock()
        self._dirty = False
        self._blocked_notified = False
        self._timer: threading.Timer | None = None

        # key → (arrival ts, StarPos) for systems arrived in this process.
        self._arrivals: dict[str, tuple[str, list]] = {}
        # key → region reported by the game in a CodexEntry.
        self._codex_regions: dict[str, str] = {}

        self._load()

    # ── CSV I/O ────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        raw = self.path.read_bytes()
        self._bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        self._newline = "\r\n" if "\r\n" in text[:4096] else "\n"

        reader = csv.DictReader(io.StringIO(text, newline=""))
        self._fields: list[str] = list(reader.fieldnames or [])
        for col in SURVEY_COLUMNS:
            if col not in self._fields:
                self._fields.append(col)
        self._rows: list[dict] = [
            {f: (row.get(f) or "") for f in self._fields} for row in reader
        ]
        self._index = {system_key(r["system_name"]): r for r in self._rows}
        log.info("Survey: loaded %d candidate systems from %s", len(self._rows), self.path.name)

    def flush(self) -> bool:
        """Write pending changes.  Returns False if the file is locked (a retry
        is scheduled and on_write_blocked is called once per lock episode)."""
        with self._lock:
            if not self._dirty:
                return True
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=self._fields, lineterminator=self._newline)
            w.writeheader()
            w.writerows(self._rows)
            data = buf.getvalue().encode("utf-8-sig" if self._bom else "utf-8")

            tmp = self.path.with_name(self.path.name + ".tmp")
            try:
                backup = self.path.with_name(self.path.stem + ".orig" + self.path.suffix)
                if not backup.exists():
                    shutil.copy2(self.path, backup)
                tmp.write_bytes(data)
                os.replace(tmp, self.path)
            except OSError as exc:
                log.warning("Survey: could not write %s (%s) — will retry in %.0fs.",
                            self.path.name, exc, self._retry_seconds)
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                self._schedule_retry()
                if self._on_write_blocked and not self._blocked_notified:
                    self._blocked_notified = True
                    self._on_write_blocked(
                        f"{self.path.name} is locked (open in Excel?). "
                        f"Survey updates are held and will be written when it's closed."
                    )
                return False

            self._dirty = False
            self._blocked_notified = False
            if self._timer:
                self._timer.cancel()
                self._timer = None
            log.debug("Survey: wrote %s", self.path.name)
            return True

    def _schedule_retry(self) -> None:
        if self._timer and self._timer.is_alive():
            return
        self._timer = threading.Timer(self._retry_seconds, self.flush)
        self._timer.daemon = True
        self._timer.start()

    def close(self) -> None:
        self.flush()
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None

    # ── Event entry point ──────────────────────────────────────────────────────

    def on_event(self, ev: dict, commander: "str | None") -> None:
        """Feed one journal event.  commander is the session's CMDR name."""
        event = ev.get("event", "")
        ts    = ev.get("timestamp", "")
        with self._lock:
            if event in ("FSDJump", "Location", "CarrierJump"):
                changed = self._on_arrival(ev, ts)
            elif event == "Scan":
                changed = self._on_scan(ev, ts)
            elif event == "FSSAllBodiesFound":
                changed = self._on_all_bodies(ev, ts, commander)
            elif event == "CodexEntry":
                changed = self._on_codex(ev)
            else:
                return
            if changed:
                self._dirty = True
                if self.autoflush:
                    self.flush()

    # ── Handlers (return True if a cell changed) ───────────────────────────────

    def _on_arrival(self, ev: dict, ts: str) -> bool:
        name = ev.get("StarSystem", "")
        if not name:
            return False
        key = system_key(name)
        self._arrivals[key] = (ts, ev.get("StarPos") or [])
        row = self._index.get(key)
        if row is None:
            return False
        return self._fill(row, "visited_utc", ts) | self._fill_region(row, key)

    def _on_scan(self, ev: dict, ts: str) -> bool:
        # Only the arrival star (DistanceFromArrivalLS == 0) says whether the
        # *system* was discovered.  BodyID 0 is the barycentre in binaries.
        if "StarType" not in ev or ev.get("DistanceFromArrivalLS") != 0:
            return False
        if "WasDiscovered" not in ev:
            return False
        name = ev.get("StarSystem", "")
        if not name:
            return False
        key = system_key(name)
        was_discovered = bool(ev["WasDiscovered"])

        row = self._index.get(key)
        if row is None:
            if was_discovered or not name.lower().startswith(self._sector_prefix):
                return False
            row = self._append_serendipitous(name)

        arrival_ts = self._arrivals.get(key, (ts, []))[0]
        changed  = self._fill(row, "discovered", "discovered" if was_discovered else "new")
        changed |= self._fill(row, "visited_utc", arrival_ts)
        changed |= self._fill_region(row, key)
        return changed

    def _on_all_bodies(self, ev: dict, ts: str, commander: "str | None") -> bool:
        row = self._index.get(system_key(ev.get("SystemName", "")))
        if row is None or row["completed"]:
            return False
        row["completed"]     = commander or "unknown"
        row["completed_utc"] = ts
        return True

    def _on_codex(self, ev: dict) -> bool:
        name   = ev.get("System", "")
        region = ev.get("Region_Localised", "")
        if not name or not region:
            return False
        key = system_key(name)
        self._codex_regions[key] = region
        row = self._index.get(key)
        if row is None or row["region"] == region:
            return False
        if row["region"]:
            log.info("Survey: %s region corrected %r → %r (CodexEntry)",
                     row["system_name"], row["region"], region)
        row["region"] = region
        return True

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _fill(row: dict, col: str, value: str) -> bool:
        if row[col] or not value:
            return False
        row[col] = value
        return True

    def _fill_region(self, row: dict, key: str) -> bool:
        if row["region"]:
            return False
        region = self._codex_regions.get(key)
        if region is None:
            pos = self._arrivals.get(key, ("", []))[1]
            if len(pos) == 3:
                found = find_region(*pos)
                region = found[1] if found else None
        return self._fill(row, "region", region or "")

    def _append_serendipitous(self, name: str) -> dict:
        row = {f: "" for f in self._fields}
        row.update(system_name=name, edsm_status="not_in_edsm", direction="serendipitous")
        p = parse_system_name(name)
        if p:
            parts = {
                "family":      f"{p['sector']} {p['subsector']}",
                "subsector":   p["subsector"],
                "mass_prefix": f"{p['mass_code']}{p['boxel']}",
                "mass_code":   p["mass_code"],
                "boxel":       str(p["boxel"]),
                "number":      str(p["number"]),
            }
            row.update({k: v for k, v in parts.items() if k in row})
        self._rows.append(row)
        self._index[system_key(name)] = row
        log.info("Survey: serendipitous undiscovered system %s appended.", name)
        return row

    # ── Reporting ──────────────────────────────────────────────────────────────

    def summary(self) -> dict[str, int]:
        with self._lock:
            rows = self._rows
            return {
                "candidates":    sum(r["direction"] != "serendipitous" for r in rows),
                "serendipitous": sum(r["direction"] == "serendipitous" for r in rows),
                "visited":       sum(bool(r["visited_utc"]) for r in rows),
                "new":           sum(r["discovered"] == "new" for r in rows),
                "discovered":    sum(r["discovered"] == "discovered" for r in rows),
                "completed":     sum(bool(r["completed"]) for r in rows),
            }

    def summary_text(self) -> str:
        s = self.summary()
        return (f"Survey: {s['completed']}/{s['candidates'] + s['serendipitous']} complete  |  "
                f"{s['new']} new, {s['discovered']} pre-discovered  |  "
                f"+{s['serendipitous']} serendipitous")


def replay_events(survey: SurveyTracker, events: "list[tuple[str, str]]") -> None:
    """Replay (event_type, raw_json) pairs, oldest first, into survey.
    Tracks the session commander from Commander / LoadGame events."""
    import json
    commander: str | None = None
    survey.autoflush = False
    for event_type, raw in events:
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        if event_type == "Commander":
            commander = ev.get("Name") or commander
        elif event_type == "LoadGame":
            commander = ev.get("Commander") or commander
        else:
            survey.on_event(ev, commander)
    survey.autoflush = True
    survey.flush()
