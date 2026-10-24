"""
Sector survey tracker.

Keeps a Sector Surveyor candidate CSV (one row per system believed to exist
but unreported to EDSM) up to date as the commander flies the sector:

  discovered     "new" if the arrival star's Scan says WasDiscovered=false,
                 else "discovered"
  completed      commander name, on FSSAllBodiesFound
  region         galactic region (CodexEntry Region_Localised when the game
                 reports one, else derived from StarPos via engine.regionmap)
  visited_utc    first arrival timestamp
  completed_utc  FSSAllBodiesFound timestamp
  resolution     clustered files only — set by the commander ("not_found",
                 "done_by_other", ...); any non-empty value resolves the row

Undiscovered in-sector systems missing from the CSV are appended with
direction="serendipitous".  Discovered systems missing from the CSV are ignored.

Two input formats, detected from the header
-------------------------------------------
* Plain candidate list — system_name, edsm_status, direction, ...
* Clustered candidates (Sector Surveyor 1.6.0+) — adds visit_order and
  survey_region (R01…Rnn).  Each claimed survey region is a unit of work:
  once every row in it is resolved, the parser closes the active leg named
  after it on the next FSDJump away (see LegManager.on_regions_complete).
  Pre-1.6.0 builds named survey_region "region", colliding with the
  tracker's galactic-region column; those files are refused.

Write rules
-----------
* First value wins for the tracker's own columns: a non-empty cell is never
  overwritten, so replaying journals is idempotent.  The one exception is
  region — the game's CodexEntry region replaces a map-derived one, because
  the map is ~49 ly per cell and misreads systems near region boundaries.
* Edits made to the file while the tracker runs are merged in before each
  write (and before region checks) whenever the file's mtime changes:
  resolution and the source columns take the disk value, the tracker's own
  columns keep the in-memory value when it has one.
* The CSV is rewritten atomically (temp file + os.replace) and keeps its
  BOM / line endings.  If the file is locked (open in Excel), changes stay in
  memory and the write is retried on a timer.
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
RESOLUTION = "resolution"
COMPLETE_WHEN = ("completed", "visited")

# Procedural name: "<Sector> AB-C d12-34".  The "12-" part is omitted by the
# game when it is 0 ("NA-A d3" == "NA-A d0-3").
_NAME_RE = re.compile(
    r"^(?P<sector>.+?) (?P<sub>[A-Z]{2}-[A-Z]) (?P<mc>[a-h])(?:(?P<n1>\d+)-)?(?P<n2>\d+)$",
    re.IGNORECASE,
)
_SURVEY_REGION_RE = re.compile(r"^R\d+$")


class SurveyFormatError(ValueError):
    """The candidate CSV can't be used as-is (e.g. a pre-1.6.0 clustered file)."""


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


def detect_format(fields: "list[str]", rows: "list[dict]") -> str:
    """Return "clustered" or "plain"; raise SurveyFormatError for pre-1.6.0
    clustered files whose survey-region column is named "region"."""
    if "survey_region" in fields and "visit_order" in fields:
        return "clustered"
    if ("cluster" in fields or "visit_order" in fields) and "region" in fields:
        if any(_SURVEY_REGION_RE.match(r.get("region") or "") for r in rows):
            raise SurveyFormatError(
                "This clustered candidates file was made by a Sector Surveyor build "
                "before 1.6.0: its survey-region column is named 'region', which "
                "collides with the tracker's galactic-region column. Regenerate it "
                "with Sector Surveyor 1.6.0 or later (column 'survey_region')."
            )
    return "plain"


def _read_csv(path: Path) -> "tuple[list[str], list[dict], bool, str]":
    """(fieldnames, rows, has_bom, newline) for a CSV file."""
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = list(reader.fieldnames or [])
    rows = [{f: (row.get(f) or "") for f in fields} for row in reader]
    newline = "\r\n" if "\r\n" in text[:4096] else "\n"
    return fields, rows, raw.startswith(b"\xef\xbb\xbf"), newline


class SurveyTracker:
    def __init__(
        self,
        csv_path: Path,
        sector: str,
        on_write_blocked: "Callable[[str], None] | None" = None,
        retry_seconds: float = 30.0,
        regions: "list[str] | None" = None,
        complete_when: str = "completed",
    ) -> None:
        self.path = Path(csv_path)
        self._sector_prefix = sector.lower().strip() + " "
        self._on_write_blocked = on_write_blocked
        self._retry_seconds = retry_seconds
        if complete_when not in COMPLETE_WHEN:
            raise ValueError(f"region_complete_when must be one of {COMPLETE_WHEN}")
        self._explored_col = "completed" if complete_when == "completed" else "visited_utc"

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
        # Survey region of the most recently visited candidate (next target).
        self._active_region: str | None = None

        self._load()
        self._claimed = self._resolve_claims(regions)

    # ── CSV I/O ────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        fields, rows, self._bom, self._newline = _read_csv(self.path)
        self.format = detect_format(fields, rows)
        self._fields = fields
        own = SURVEY_COLUMNS + ([RESOLUTION] if self.clustered else [])
        for col in own:
            if col not in self._fields:
                self._fields.append(col)
        self._rows: list[dict] = [{f: r.get(f, "") for f in self._fields} for r in rows]
        self._index = {system_key(r["system_name"]): r for r in self._rows}
        self._mtime_ns = self.path.stat().st_mtime_ns
        if self.clustered:
            visited = [r for r in self._rows if r["survey_region"] and r["visited_utc"]]
            if visited:
                self._active_region = max(visited, key=lambda r: r["visited_utc"])["survey_region"]
        log.info("Survey: loaded %d candidate systems (%s format) from %s",
                 len(self._rows), self.format, self.path.name)

    @property
    def clustered(self) -> bool:
        return self.format == "clustered"

    def _refresh(self) -> bool:
        """Merge edits made to the file since we last read or wrote it.
        Returns False if the file couldn't be read."""
        try:
            mtime = self.path.stat().st_mtime_ns
        except OSError:
            return True  # file gone: our next write recreates it
        if mtime == self._mtime_ns:
            return True
        try:
            fields, rows, _, _ = _read_csv(self.path)
            detect_format(fields, rows)
        except (OSError, UnicodeDecodeError, csv.Error, SurveyFormatError) as exc:
            log.warning("Survey: could not read edits from %s (%s).", self.path.name, exc)
            return False
        self._merge(fields, rows)
        self._mtime_ns = mtime
        return True

    def _merge(self, fields: "list[str]", rows: "list[dict]") -> None:
        own = set(SURVEY_COLUMNS)
        for f in fields:
            if f not in self._fields:
                self._fields.append(f)
                for r in self._rows:
                    r[f] = ""
        changed = False
        for disk in rows:
            key = system_key(disk.get("system_name", ""))
            mem = self._index.get(key)
            if mem is None:
                # Row added by hand: keep it.
                mem = {f: "" for f in self._fields}
                self._rows.append(mem)
                self._index[key] = mem
            for f in fields:
                value = disk.get(f, "")
                if f in own:
                    if not mem[f] and value:       # tracker's column: memory wins
                        mem[f] = value
                    elif mem[f] != value:
                        changed = True             # our value isn't on disk yet
                elif mem[f] != value:              # resolution & source columns: disk wins
                    mem[f] = value
        # Rows only in memory (appended, not yet written) are kept.
        if changed or len(rows) != len(self._rows):
            self._dirty = True
        log.info("Survey: merged external edits from %s", self.path.name)

    def flush(self) -> bool:
        """Write pending changes.  Returns False if the file is locked (a retry
        is scheduled and on_write_blocked is called once per lock episode)."""
        with self._lock:
            if not self._refresh():
                return self._blocked("can't be read")
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
                self._mtime_ns = self.path.stat().st_mtime_ns
            except OSError as exc:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                return self._blocked(f"is locked ({exc})")

            self._dirty = False
            self._blocked_notified = False
            if self._timer:
                self._timer.cancel()
                self._timer = None
            log.debug("Survey: wrote %s", self.path.name)
            return True

    def _blocked(self, why: str) -> bool:
        log.warning("Survey: %s %s — will retry in %.0fs.", self.path.name, why, self._retry_seconds)
        self._schedule_retry()
        if self._on_write_blocked and not self._blocked_notified:
            self._blocked_notified = True
            self._on_write_blocked(
                f"{self.path.name} is locked (open in Excel?). "
                f"Survey updates are held and will be written when it's closed."
            )
        return False

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

    def resolve(self, system_name: str, value: str) -> bool:
        """Set a row's resolution (e.g. "not_found"; "" clears it).
        Returns False if the system isn't in the file."""
        if not self.clustered:
            raise SurveyFormatError(
                "resolution is only tracked for clustered candidate files.")
        with self._lock:
            self._refresh()
            row = self._index.get(system_key(system_name))
            if row is None:
                return False
            if row[RESOLUTION] != value:
                row[RESOLUTION] = value
                self._dirty = True
            return True

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
        if row.get("survey_region"):
            self._active_region = row["survey_region"]
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
        parts = {"system_name": name, "edsm_status": "not_in_edsm",
                 "direction": "serendipitous"}
        p = parse_system_name(name)
        if p:
            parts.update({
                "family":      f"{p['sector']} {p['subsector']}",
                "subsector":   p["subsector"],
                "mass_prefix": f"{p['mass_code']}{p['boxel']}",
                "mass_code":   p["mass_code"],
                "boxel":       str(p["boxel"]),
                "number":      str(p["number"]),
                "boxel_id":    f"{p['subsector']} {p['mass_code']}{p['boxel']}",
            })
        # Only columns this CSV actually has.
        row.update({k: v for k, v in parts.items() if k in row})
        self._rows.append(row)
        self._index[system_key(name)] = row
        log.info("Survey: serendipitous undiscovered system %s appended.", name)
        return row

    # ── Survey regions (clustered files) ───────────────────────────────────────

    def _resolve_claims(self, regions: "list[str] | None") -> "list[str]":
        """Survey regions that count toward legs/completion, in file order."""
        if not self.clustered:
            return []
        in_file = list(dict.fromkeys(r["survey_region"] for r in self._rows if r["survey_region"]))
        if not regions:
            return in_file
        wanted = [r.upper().strip() for r in regions]
        missing = [r for r in wanted if r not in in_file]
        if missing:
            log.warning("Survey: claimed region(s) %s not found in %s", missing, self.path.name)
        return [r for r in in_file if r in wanted]

    @property
    def regions(self) -> "list[str]":
        """Claimed survey regions (all regions in the file if none claimed)."""
        return list(self._claimed)

    def _resolved(self, row: dict) -> bool:
        return bool(row.get(RESOLUTION) or row[self._explored_col])

    def region_progress(self) -> "dict[str, tuple[int, int]]":
        """{region: (resolved, total)} for the claimed regions."""
        with self._lock:
            prog = {r: [0, 0] for r in self._claimed}
            for row in self._rows:
                p = prog.get(row.get("survey_region", ""))
                if p is not None:
                    p[1] += 1
                    p[0] += self._resolved(row)
            return {r: (done, total) for r, (done, total) in prog.items()}

    def complete_regions(self) -> "list[str]":
        """Claimed regions whose every row is resolved (re-reads edits first)."""
        with self._lock:
            self._refresh()
            return [r for r, (done, total) in self.region_progress().items() if done == total]

    def region_rows(self, regions: "list[str]") -> "tuple[list[str], list[list[str]]]":
        """(headers, rows) for the given survey regions, in file order."""
        with self._lock:
            wanted = set(regions)
            return list(self._fields), [
                [r[f] for f in self._fields]
                for r in self._rows if r.get("survey_region") in wanted
            ]

    def next_target(self) -> "dict | None":
        """Lowest-visit_order unresolved row in the active region, else in the
        other claimed regions.  Route order, not distance."""
        if not self.clustered:
            return None
        with self._lock:
            claimed = set(self._claimed)
            pending = [r for r in self._rows
                       if r["survey_region"] in claimed and r["visit_order"]
                       and not self._resolved(r)]
            if not pending:
                return None
            active = [r for r in pending if r["survey_region"] == self._active_region]
            return dict(min(active or pending, key=lambda r: int(r["visit_order"])))

    # ── Reporting ──────────────────────────────────────────────────────────────

    def summary(self) -> dict[str, int]:
        with self._lock:
            rows = self._rows
            s = {
                "candidates":    sum(r.get("direction") != "serendipitous" for r in rows),
                "serendipitous": sum(r.get("direction") == "serendipitous" for r in rows),
                "visited":       sum(bool(r["visited_utc"]) for r in rows),
                "new":           sum(r["discovered"] == "new" for r in rows),
                "discovered":    sum(r["discovered"] == "discovered" for r in rows),
                "completed":     sum(bool(r["completed"]) for r in rows),
            }
            if self.clustered:
                prog = self.region_progress()
                s["resolved"]          = sum(self._resolved(r) for r in rows)
                s["not_found"]         = sum(r[RESOLUTION] == "not_found" for r in rows)
                s["regions_claimed"]   = len(prog)
                s["regions_complete"]  = sum(d == t for d, t in prog.values())
            return s

    def short_status(self) -> str:
        """Compact progress for the tray tooltip."""
        with self._lock:
            if not self.clustered:
                return f"Survey {self.summary()['completed']} done"
            region = self._focus_region()
            if region is None:
                return "Survey: all claimed regions complete"
            done, total = self.region_progress()[region]
            return f"{region} {done}/{total}"

    def _focus_region(self) -> "str | None":
        """Active region if it's claimed and unfinished, else the next target's."""
        prog = self.region_progress()
        if self._active_region in prog:
            done, total = prog[self._active_region]
            if done < total:
                return self._active_region
        nxt = self.next_target()
        return nxt["survey_region"] if nxt else None

    def summary_text(self) -> str:
        s = self.summary()
        if not self.clustered:
            return (f"Survey: {s['completed']}/{s['candidates'] + s['serendipitous']} complete  |  "
                    f"{s['new']} new, {s['discovered']} pre-discovered  |  "
                    f"+{s['serendipitous']} serendipitous")
        with self._lock:
            parts = []
            region = self._focus_region()
            if region:
                done, total = self.region_progress()[region]
                parts.append(f"{region}: {done}/{total} resolved")
            nxt = self.next_target()
            if nxt:
                parts.append(f"next #{nxt['visit_order']} {nxt['system_name']}")
            parts.append(f"regions {s['regions_complete']}/{s['regions_claimed']} complete")
            parts.append(f"{s['new']} new, {s['not_found']} not found, "
                         f"+{s['serendipitous']} serendipitous")
            return "  |  ".join(parts)


def make_survey(cfg: dict, on_write_blocked: "Callable[[str], None] | None" = None
                ) -> "SurveyTracker | None":
    """SurveyTracker for cfg's [survey] block, or None if there isn't one."""
    survey_cfg = cfg.get("survey") or {}
    if not survey_cfg.get("csv_path"):
        return None
    return SurveyTracker(
        survey_cfg["csv_path"], cfg["sector"],
        on_write_blocked=on_write_blocked,
        regions=survey_cfg.get("regions"),
        complete_when=survey_cfg.get("region_complete_when", "completed"),
    )


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
