# ED Expedition Ledger

<img src="icon.png" alt="ED Expedition Ledger" width="120">

A configurable real-time journal watcher for multi-leg exploration expeditions
in Elite Dangerous.

Define your planned route — start system, waypoints, and final destination — in
`config.toml`. The tracker reads your game's session journals as you play,
records every jump, scan, and discovery into a local SQLite database, and
generates per-leg Excel + CSV summaries automatically when you reach each
waypoint.

---

## Contents

| Path | What it is |
|---|---|
| `tracker.pyw` | Main entry point (tray + CLI + validate modes) |
| `engine/` | Core engine — fully testable without the tray |
| `tray/app.py` | Thin pystray shell over the engine |
| `config.toml` | All user-editable settings |
| `config_hypiae_aim.toml` | Sector-survey config (see [Sector survey mode](#sector-survey-mode)) |
| `data/sector-surveyor_output/` | Sector-surveyor candidate CSVs the survey keeps updated |
| `requirements.txt` | Pinned Python dependencies |
| `make_shortcut.py` | Creates a Desktop .lnk shortcut |
| `tests/` | pytest suite (unit + full-expedition validation) |
| `output/` | Generated leg exports land here (auto-created) |
| `tracker.db` | SQLite database (auto-created) |
| `tracker.log` | Rotating log (auto-created) |
| `LICENSE` | MIT License |

---

## Install

### Windows app (recommended)

Run `EDLedger-Setup-1.0.0.exe`. It installs per user (no admin rights) to
`%LOCALAPPDATA%\Programs\EDLedger`, adds **ED Expedition Ledger** to the
Desktop and Start menu (plus a Start-menu **Configure expedition** entry), and
needs no Python. The app isn't code-signed, so Windows SmartScreen may ask you
to confirm the first time ("More info" → "Run anyway").

On first launch the configuration window opens: set the expedition up and
click **Save**, and the tracker starts in the system tray. Everything you
create lives outside the install folder, so re-running a newer installer
upgrades in place and never touches it:

| What | Where |
|---|---|
| Expedition config | `%APPDATA%\EDLedger\config.toml` |
| Database, log, validation baseline | `%LOCALAPPDATA%\EDLedger\` |
| Exports (default; changeable in the config window) | `%LOCALAPPDATA%\EDLedger\output\` |

Tray → **Open output folder** opens the exports. The command-line functions
(`--survey-resolve`, `--close-leg`, `--survey-rebuild`, `--cli`, `--validate`)
are in the console build next to the app:

```
"%LOCALAPPDATA%\Programs\EDLedger\EDLedger-cli.exe" --survey-resolve "Hypiae Aim XD-R c18-1"
```

It uses the installed app's config unless you pass `--config`.

**Building the installer** (needs Python 3.11+, the packages in
`requirements.txt` and `requirements-build.txt`, and
[Inno Setup 6](https://jrsoftware.org/isdl.php)): run `build.bat`. It makes
`ledger.ico` from `icon.png`, builds the PyInstaller bundle (`EDLedger.spec`:
`EDLedger.exe` windowed and `EDLedger-cli.exe` console, sharing one
`_internal` folder) and compiles `installer.iss` into
`dist-installer\EDLedger-Setup-<version>.exe`. Bump the version in
`engine/__init__.py`, `version_info.txt` and `installer.iss` together.

### From source

1. **Python 3.11+** required — download from [python.org](https://python.org) if
   needed. Tick **"Add Python to PATH"** during install.

2. Clone or download this repository somewhere permanent (the tracker writes
   `tracker.db` and `output/` relative to its own folder):
   ```
   git clone https://github.com/jenningsmt/ed-expedition-ledger.git C:\Tools\ed-expedition-ledger
   cd C:\Tools\ed-expedition-ledger
   ```

3. **Run the installer** — either double-click `install.bat` or:
   ```
   python install.py
   ```
   This checks your Python version, installs dependencies, creates the Desktop
   shortcut, and opens the configuration window.

4. In the configuration window, fill in your commander name(s), journal
   folder, and expedition (waypoint route or sector survey), then click
   **Save**.

A source run keeps everything in the repo folder (`config.toml`,
`tracker.db`, `output/`, `tracker.log`), exactly as before; the installed
app's folders above aren't used.

---

## Configure your expedition

Open `config.toml` and fill in five things:

**`journal_dir`** — path to your ED Saved Games folder. The default is the
standard Windows location; change it if your installation is non-standard.

**`commander`** — your in-game commander name, used to filter journal events.

**`expedition_start_timestamp`** — UTC timestamp of your first expedition jump.
Every event before this time is ignored, which excludes any pre-departure
shakedown flights recorded in the same journal directory. Find it by opening
your most recent journal file and noting the timestamp of your first `FSDJump`.

**`expedition_end_system`** — the system where the expedition ends. Arriving
here closes the final leg and marks the run complete.

**`[[waypoints]]`** — one block per destination. Add as many as your route
requires. System names are matched case-insensitively. Example:

```toml
[[waypoints]]
label  = "Outpost Alpha"
system = "Beagle Point"

[[waypoints]]
label  = "Outpost Beta"
system = "Colonia"
```

---

## Create the Desktop shortcut

Run once (needs Pillow, which is already in requirements):

```
python make_shortcut.py
```

This creates `%USERPROFILE%\Desktop\ED Expedition Ledger.lnk` pointing to
`pythonw.exe tracker.pyw` with a compass-rose icon and the correct working
directory.

---

## How to use

### Session start

Double-click the Desktop shortcut (or run `pythonw tracker.pyw`).
A compass-rose icon appears in the system tray. The tracker immediately:

1. Backfills all journal files from the `expedition_start_timestamp` cutoff.
2. Starts live-tailing the active journal file.
3. Detects new journal files if the game restarts mid-session.

### During a session

- **Hover** over the tray icon to see current leg / jump count / distance / last system.
- Right-click for the full menu:

| Menu item | What it does |
|---|---|
| **Status** | Shows current leg stats as a balloon notification |
| **Export snapshot** | Exports the current in-progress leg to xlsx + CSVs without closing it, then opens the output folder. Filename is suffixed with `_snapshot_<timestamp>` so it is distinguishable from the final export. |
| **Close current leg & export now** | Closes the active leg, exports it to xlsx + CSVs, and opens a new leg |
| **Stop & exit** | Flushes the DB, stops the watcher, removes the tray icon |

### Session end

Right-click → **Stop & exit**. Never just kill the process — this ensures the
DB is cleanly closed and no partial writes are left.

---

## How legs work

| Trigger | Effect |
|---|---|
| Expedition start timestamp | Leg 1 opens automatically |
| FSDJump **away from** an unvisited waypoint | Current leg closes (named after that waypoint), next leg opens |
| FSDJump to `expedition_end_system` | Final leg closes, expedition marked **complete** |
| Manual "Close current leg & export now" | Closes active leg with an ordinal name, opens the next |

**Waypoints are unordered** — visit them in any sequence.  
**Revisiting** a waypoint you've already reached does nothing.  
**Carrier jumps** are tracked separately and never trigger a leg change.

> **Why the departure trigger?** Leg closure fires when you jump *away* from a
> waypoint, not when you arrive. This ensures that any cartographic or
> exobiology sales made while docked at the waypoint station are attributed to
> the leg that earned them — the one that ends there — rather than the new leg
> that begins with your departure jump.

---

## Editing waypoints

Open `config.toml` and edit the `[[waypoints]]` blocks. System names are
matched **case-insensitively** against `FSDJump.StarSystem`, so capitalisation
doesn't matter. Restart the tracker for changes to take effect.

---

## Waypoint-only exports

For a checklist-style survey expedition -- e.g. verifying a list of candidate
systems from an external source rather than exploring a contiguous route --
you often want exports to cover only the designated waypoints, not every
system transited between them. Set in `config.toml`:

```toml
waypoints_only_export = true
```

With this on, every export (per-leg xlsx/CSVs and `master_rollup.xlsx`)
restricts **Systems, Bodies, Terraformable & Notable, Body Classes, Organics,
Codex Firsts, and Rare Finds** to just the systems listed under
`[[waypoints]]`. Each export's Summary sheet gets a `Note` row confirming
this is active and how many systems it covers.

**Sales figures are the one exception** — Cartographics and Exo-Bio sales
always cover the whole leg/expedition regardless of this setting, because
Frontier's own `MultiSellExplorationData`/`SellOrganicData` journal events
don't record per-system or per-sale-item earnings breakdowns. The tracker
already records *which* systems contributed to a cartographics sale (see
the `sales_cartographics_systems` table), but not each one's share of the
total credits, so there's no reliable way to isolate "sales earned from
waypoint systems only" — the underlying data to do that correctly doesn't
exist in the journal. Treat sales totals as whole-leg/whole-expedition even
with `waypoints_only_export` on.

Default is `false` (unset behaves the same way) — existing configs and
route-based expeditions are unaffected.

---

## Sector survey mode

For surveying a whole sector rather than flying to waypoints — e.g. working
through an ED Sector Surveyor list of systems that likely
exist but have never been reported to EDSM. A ready-made config is
`config_hypiae_aim.toml`; run it alongside (not instead of) a waypoint
expedition, since it has its own database and output folder:

```
pythonw tracker.pyw --config config_hypiae_aim.toml          # tray
python  tracker.pyw --config config_hypiae_aim.toml --cli    # headless
python  make_shortcut.py --config config_hypiae_aim.toml --name "ED Ledger - Hypiae Aim"
```

Key settings:

```toml
commanders = ['AristonX', 'DovakiinMJ']   # several CMDRs, one journal folder
mode       = 'sector'
sector     = 'Hypiae Aim'
output_dir    = "output_hypiae_aim"
db_path       = "tracker_hypiae_aim.db"
baseline_path = "validation_baseline_hypiae_aim.json"

[survey]
csv_path = 'data/sector-surveyor_output/hypiae_aim_unreported_systems.csv'
```

### Two candidate-file formats

The format is detected from the CSV header; there is no config switch.

| Format | File | Header has | Legs |
|---|---|---|---|
| **Plain list** | `<sector>_unreported_systems.csv` | `system_name, edsm_status, direction, …` | one open sector leg |
| **Clustered** (Sector Surveyor 1.6.0+) | `<sector>_candidates_clustered.csv` | `visit_order, survey_region, …` | one leg per survey region (R01…Rnn) — see [Survey regions](#survey-regions-clustered-files) |

Clustered files made by Sector Surveyor builds before 1.6.0 named the
survey-region column `region`, which collides with the tracker's own
galactic-region column. The tracker refuses such a file (a `visit_order` /
`cluster` header with `R01`-style values under `region`) and asks you to
regenerate it with 1.6.0 or later, rather than overwrite those values.

### Exploration exports

Sector mode keeps one open leg at a time (there are no waypoints or end
system). The open leg's exports are named by their *as-of* UTC date —
`sector_hypiae_aim_2026-10-23.xlsx`, `sector_hypiae_aim_2026-10-23_bodies.csv`,
and so on — plus `master_rollup.xlsx`. They refresh after the startup
backfill, when the game writes its `Shutdown` event, on tray → **Export
snapshot**, and when the tracker exits. Re-exporting on the same UTC day
overwrites that day's files; each earlier day's set stays as a snapshot.
With a plain list the open leg spans the whole survey, so these exports are
cumulative.

A **closed** leg is exported under its own name and close date, without the
`sector_` prefix — a survey region closing on 2 Nov writes:

```
hypiae_aim_R14_2026-11-02.xlsx
hypiae_aim_R14_2026-11-02_bodies.csv          hypiae_aim_R14_2026-11-02_rare_finds.csv
hypiae_aim_R14_2026-11-02_body_classes.csv    hypiae_aim_R14_2026-11-02_sales.csv
hypiae_aim_R14_2026-11-02_codex.csv           hypiae_aim_R14_2026-11-02_systems.csv
hypiae_aim_R14_2026-11-02_organics.csv        hypiae_aim_R14_2026-11-02_terraformable.csv
hypiae_aim_R14_2026-11-02_candidates.csv      (survey-region legs only)
hypiae_aim_R14_2026-11-02_master_rollup.xlsx  (the master rollup as of this close)
```

Regions closing together give `hypiae_aim_R01_R02_<date>_*`; a leg closed by
hand as "Hypiae Aim (pre-regions)" gives `hypiae_aim_pre-regions_<date>_*`.
`master_rollup.xlsx` itself is rewritten on every export.

Systems and Bodies carry a **Commander** column. Systems also says how each
system relates to the survey, so targets and the systems flown through to
reach them can be told apart:

| Column | Values |
|---|---|
| `Discovery` | `new` (undiscovered on arrival) or `previously discovered`, from the arrival star's scan; blank if it was never scanned (e.g. arrived by carrier) |
| `Survey Role` | `target` — a candidate in a claimed region; `other-region candidate` — on the list but in a region you didn't claim; `serendipitous` — undiscovered, in the sector, not on the list (also appended to the CSV); `transit` — anything else |
| `Survey Region`, `Visit Order` | from the candidate file, for listed systems |

The Summary sheet counts them: targets visited (new / previously
discovered), other-region candidates, serendipitous systems and transit
systems (new / previously discovered). `Discovery` appears in waypoint
exports too; the survey columns only with a candidate file.

Only systems in the loaded file can be told apart: with a file holding just
your regions, an undiscovered candidate from another region shows as
`serendipitous` (or `transit` if already discovered). Load the full file with
`regions = [...]` to have those labelled `other-region candidate`.

### Survey CSV tracking

The tracker keeps the candidate CSV up to date as you fly, adding five
columns (six for clustered files):

| Column | Filled when | Value |
|---|---|---|
| `discovered` | arrival star is scanned | `new` (`WasDiscovered=false`) or `discovered` |
| `completed` | `FSSAllBodiesFound` | commander name (`AristonX` / `DovakiinMJ`) |
| `region` | arrival | galactic region, e.g. `Elysian Shore` |
| `visited_utc` | first arrival | journal timestamp |
| `completed_utc` | `FSSAllBodiesFound` | journal timestamp |
| `resolution` | *clustered only* — set by you | `not_found`, `done_by_other`, … |

- **Serendipitous systems** — an undiscovered system in the sector that
  isn't in the CSV is appended at the end with `direction = serendipitous`,
  `edsm_status = not_in_edsm`, and family/subsector/mass/boxel/number parsed
  from its name (only for columns the file has). In a clustered file it has
  no `survey_region` or `visit_order`, so it never belongs to a region leg.
  Already-discovered systems not in the CSV are ignored, as are undiscovered
  systems outside the sector.
- **First value wins** — a filled tracker cell is never overwritten, so a
  revisit after the data was sold (now "discovered"), or the other commander
  finishing a system second, doesn't change the record.
- **Editing the file while the tracker runs** is safe. Before each write
  (and before each region check) the tracker re-reads the file if its
  modification time changed and merges your edits:
  - `resolution` and the Sector Surveyor columns take **your** value — so
    clearing a mistaken `not_found` works;
  - the tracker's own five columns keep the tracker's value when it has
    one, and take yours only if its cell is empty — so Excel reformatting
    `visited_utc` on save, say, is undone on the next write;
  - added columns and hand-added rows are kept. Deleting a row the tracker
    still holds doesn't stick: it is written back.

  Excel locks the file while it's open, so edits made there land when you
  save **and close** it.
- **Region** comes from the game's `CodexEntry` when one fires in the system
  (authoritative), otherwise from the star's coordinates via
  [klightspeed's region map](https://github.com/klightspeed/EliteDangerousRegionMap)
  (MIT, vendored in `engine/regionmap*.py`). Checked against 1,172 journal
  `CodexEntry` regions, the map agrees on 98.4%; disagreements are all
  within one ~49 ly map cell of a region boundary — and the Elysian Shore /
  Formidine Rift boundary runs through Hypiae Aim. A later `CodexEntry`
  corrects a map-derived region.
- **System discovery** is read from the *arrival* star's `Scan`
  (`DistanceFromArrivalLS == 0`), not `BodyID 0`, which is the barycentre
  in binary systems.
- **Name matching** treats the game's short form `Hypiae Aim NA-A d3` as
  equal to `Hypiae Aim NA-A d0-3`.
- **Writes are atomic** (temp file + replace) and keep the file's row order,
  UTF-8 BOM (or lack of one) and line endings. The untouched original is
  kept once as `*.orig.csv`.
- **Open in Excel?** Excel locks the file. Updates are held in memory, a tray
  notification says so, and the write is retried every 30 s until the file
  is closed. Open a *copy* if you want to browse it mid-session.

**Replacing the CSV** (e.g. after re-running Sector Surveyor): stop the
tracker, drop in the new file, then replay everything already flown:

```
python tracker.pyw --config config_hypiae_aim.toml --survey-rebuild
```

The rebuild only fills the CSV; it doesn't touch legs or exports. Values
already in the new file are kept, and `resolution` marks aren't journal
events, so they aren't replayed — carry them over by hand or with
`--survey-resolve`.

### Survey regions (clustered files)

A clustered file from Sector Surveyor 1.6.0+ lists every candidate in a
planned route order (`visit_order` 1…N) and groups them into **survey
regions** R01…Rnn. Each region is a unit of work: when every candidate in it
is **resolved**, the tracker closes the active leg named after the region
(`R01`), exports it, and opens the next — the same way reaching a waypoint
does.

```toml
[survey]
csv_path = 'data/input_data/hypiae_aim_candidates_clustered.csv'
regions  = ['R01', 'R14']              # optional claim filter (default: all regions)
region_complete_when = 'completed'     # or 'visited'
```

- **Resolved** means *explored* or *marked*. Explored follows
  `region_complete_when`: `completed` (default) needs `FSSAllBodiesFound`,
  i.e. a full FSS; `visited` only needs an arrival. Marked means any
  non-empty `resolution`.
- **Marking candidates.** Many candidates don't exist — the game never used
  that name, and nothing in the journal says so. Mark them so their region
  can close. Use `not_found` for a name the galaxy map doesn't find, and
  `done_by_other` for one a squadmate explored (their journals aren't
  yours). Type it into the `resolution` column, or from the command line —
  safe while the tracker runs:

  ```
  python tracker.pyw --config config_hypiae_aim.toml --survey-resolve "Hypiae Aim XD-R c18-1" "Hypiae Aim XD-R c18-0"
  python tracker.pyw --config config_hypiae_aim.toml --survey-resolve "Hypiae Aim XD-R c18-1" --as done_by_other
  python tracker.pyw --config config_hypiae_aim.toml --survey-resolve "Hypiae Aim XD-R c18-1" --as clear
  ```
- **When a leg closes.** On the next FSDJump *away* after the region becomes
  complete — as with waypoints — so scans and sales made in the last system
  land in the closing leg. Regions can be finished in any order. If several
  finish together they close one leg, e.g. `R01 + R02`. A region never
  closes twice, even after a restart. When every claimed region has closed,
  the expedition is marked complete; the CSV is still updated after that.
- **Claim filter.** With `regions` set, only those regions get legs and
  count toward completion. Rows from other regions are still tracked if you
  visit them. Leave it out to work the whole file — so a squadron member can
  load the full shared file rather than splitting it.
- **Rows without a region** (candidates Sector Surveyor couldn't place, and
  serendipitous systems) are tracked but never hold up a region.
- **Legs are time slices, not region slices.** A leg holds everything
  flown since the previous leg closed. If you alternate between R01 and
  R14, the leg named `R14` also has those R01 jumps, scans and sales.
  Systems and Bodies aren't filtered by region, so serendipitous and
  in-transit finds stay in. Each closed region leg also gets a
  **Candidates** sheet (and `_candidates.csv`) listing that region's rows
  and their status.
- **Progress and next target.** Tray → **Survey progress** (and `--cli` at
  start-up) shows e.g.
  `R14: 6/260 resolved | next #2673 Hypiae Aim XD-R c18-1 | regions 0/55 complete | …`.
  The tooltip shows `R14 6/260`. The active region is the one holding the
  candidate you visited last. The next target is its lowest unresolved
  `visit_order`, else the lowest in your other claimed regions. That's
  route order, not distance from where you are.

### Moving a plain-list survey to a clustered file

Close the leg that holds the survey so far under a name of your choice, so
the first region leg doesn't absorb everything flown before regions existed.
Then point the config at the clustered file and replay your progress into it:

1. Stop the tracker (tray → **Stop & exit**).
2. Close the open leg; this exports it as
   `hypiae_aim_pre-regions_<date>_*` and opens the next leg.
   In the app: tray → **Configure expedition…** → **Close current leg…**
   (it suggests "Hypiae Aim (pre-regions)"; this one works with the tracker
   running). From source:
   ```
   python tracker.pyw --config config_hypiae_aim.toml --close-leg "Hypiae Aim (pre-regions)"
   ```
3. In `config_hypiae_aim.toml`, set `[survey] csv_path` to the clustered file
   (and `regions` if you've claimed some).
4. Replay the progress already flown into it:
   ```
   python tracker.pyw --config config_hypiae_aim.toml --survey-rebuild
   ```
5. Start the tracker. The next leg to close is named after the first region
   you finish.

`--close-leg NAME` also works on its own in any mode: it closes the open leg
under `NAME`, opens the next and exports the closed one.

---

## CLI / headless mode

Useful for debugging or running on a server without a display:

```
python tracker.pyw --cli
```

Prints events to stdout and writes the same rotating `tracker.log`.
Press Ctrl-C to stop cleanly.

---

## Validation

The validation system has two layers that require **no manual editing** as the
expedition grows.

### Invariants

Always-true structural assertions computed fresh from the current journals
every run. Examples:
- No event has a timestamp before the expedition cutoff.
- `systems_visited <= commander_jumps`
- `distinct_bodies_scanned <= raw_scan_events` (dedup ≤ raw)
- `first_discovered ≤ bodies_scanned`

### Snapshot baseline (`validation_baseline.json`)

A regenerable JSON file that captures current cumulative metrics.
`--validate` checks that every metric is **≥ the baseline** — a decrease is a
real regression. Growth is expected and always passes.

`validation_baseline.json` is excluded from the repository (it is personal to
each commander's expedition). Generate yours with `--snapshot` after your first
session.

### Workflow after each play session

```
python tracker.pyw --validate    # catches any regression / parser bug
# eyeball the numbers look right
python tracker.pyw --snapshot    # advance the baseline to current state
```

No code edits required.

### Creating the baseline for the first time

```
python tracker.pyw --snapshot
```

### Running validate

```
python tracker.pyw --validate
```

```
=== Invariant Checks ===
  [PASS] No pre-cutoff events in DB
  [PASS] systems_visited <= commander_jumps
  [PASS] bodies_scanned: distinct <= raw
  ...
  All 11 invariants passed.

=== Baseline Comparison ===
  [OK]   commander_jumps   baseline=215  current=220  (+5)
  [OK]   distance_ly       baseline=15149.91  current=15500.12  (+350.21)
  ...
  All 21 metrics meet or exceed baseline.

PASSED.
```

Exit code 0 = all checks pass. Exit code 1 = invariant failure or metric regression.

### Running as pytest

```
pytest tests/test_validate.py -v
```

Skipped automatically when journal files are not present. The `expedition`
fixture is module-scoped so journals are ingested only once for the full class.

---

## Output files

Each leg export lands in `output/` (configurable in `config.toml`):

```
output/
  Leg01_Outpost_Alpha_2025-03-01.xlsx
  Leg01_Outpost_Alpha_2025-03-01_systems.csv
  Leg01_Outpost_Alpha_2025-03-01_bodies.csv
  Leg01_Outpost_Alpha_2025-03-01_terraformable.csv   ← terraformable + ELW/WW/AW
  Leg01_Outpost_Alpha_2025-03-01_body_classes.csv    ← per-class count breakdown
  Leg01_Outpost_Alpha_2025-03-01_organics.csv
  Leg01_Outpost_Alpha_2025-03-01_codex.csv
  Leg01_Outpost_Alpha_2025-03-01_rare_finds.csv      ← notable first discoveries
  Leg01_Outpost_Alpha_2025-03-01_sales.csv
  Leg02_Outpost_Beta_2025-03-08.xlsx
  ...
  master_rollup.xlsx         ← regenerated on every leg close
```

The xlsx has sheets: **Summary**, Systems, Bodies, Terraformable & Notable,
Body Classes, Organics, Codex Firsts, Rare Finds, Sales.

### Metric definitions

| Metric | Definition |
|---|---|
| **Bodies scanned** | Distinct `(system, body_id)` pairs from `Scan` events. A body revisited in a later session counts once. |
| **First-discovered** | Distinct bodies where `WasDiscovered == false` in the first `Scan` event. |
| **Surface-mapped** | Distinct bodies with a `SAAScanComplete` event. |
| **Terraformable bodies** | Distinct bodies where `TerraformState` is non-empty, **regardless of planet class**. This is the primary high-value exploration metric. |
| **Body-class counts** | Independent per-`PlanetClass` tallies (Water world, Earthlike body, …) and per-`StarType` tallies (G, M, K, …). Reported separately from terraformable so a terraformable HMC body is counted in both. |
| **Organic variants** | Distinct `Variant_Localised` strings where `ScanOrganic.ScanType == Analyse` (stage 3). |

The `master_rollup.xlsx` aggregates all legs with a per-leg breakdown table and
a whole-expedition summary sheet.

---

## Rare / notable first-discovery detector

The tracker evaluates every body scan against a configurable ruleset and flags
structurally notable objects. Results appear in a **Rare Finds** sheet in each
per-leg xlsx, a matching `.csv`, and a rollup breakdown in `master_rollup.xlsx`.

### Design note — why not edastro's GEC "rare" list?

edastro's GEC "rare" catalogue lists already-discovered community POIs.
You cannot be the **first discoverer** of something already on that list, so
it is the wrong source for this feature. Rarity here is **structural**: it is
computed deterministically from journal fields (`Scan`, `FSSBodySignals`),
not by matching external instances.

### Ruleset

All rules are individually toggle-able in `config.toml` under `[rarity]`.
Setting `flag_only_first_discoveries = false` evaluates all scanned bodies
and records the WasDiscovered/WasMapped/WasFootFalled flags alongside.

| # | Rule tag | Trigger |
|---|---|---|
| 1 | `ringed_habitable` | ELW / WW / AW with rings present |
| 2 | `habitable_moon` | ELW / WW / AW whose first Parent is a Planet |
| 3 | `life_bearing_gg` | Gas giant with water-based or ammonia-based life; marked ringed if applicable |
| 4 | `very_small` | Radius < `very_small_radius_m` (default 300 km) |
| 5 | `tidal_moon` | Orbits a planet (`Parents[0]` is Planet) **and** Volcanism non-empty |
| 6 | `jumponium` | Geological signals ≥ `geo_signal_threshold` (default 3) **and** Volcanism non-empty **and** ≥ 1 material in the jumponium set |
| 7 | `exotic_star` | StarType in configurable set: N, H, D\*, W\*, AeBe |
| 8 | `high_gravity` | Landable body with SurfaceGravity > `high_gravity_g` × 9.80665 m/s² (default 3 g) |
| 9 | `fast_rotator` | `|RotationPeriod|` < `fast_rotator_hours` × 3600 s (default 3 h), excluding tidal-lock |
| 10 | `ggg_candidate` | Gas giant in `ggg_planet_classes` with non-empty `AtmosphereComposition` — **best-effort heuristic, verify visually; will have false positives** |
| 11 | `nsp_alert` | System-level alert for Notable Stellar Phenomena via CodexEntry category or non-mundane `FSSSignalDiscovered` signal. |

### Jumponium set (configurable)

`Carbon`, `Vanadium`, `Germanium`, `Arsenic`, `Niobium`, `Yttrium`, `Polonium`.
Materials are matched case-insensitively against the journal `Name_Localised`
field. The `trigger_details` column records the count and names found.

### Configurable thresholds (all in `[rarity]` of `config.toml`)

| Key | Default | Meaning |
|---|---|---|
| `flag_only_first_discoveries` | `true` | Only flag bodies where `WasDiscovered == false` |
| `very_small_radius_m` | `300000` | 300 km in metres |
| `high_gravity_g` | `3.0` | Surface gravity threshold in g |
| `fast_rotator_hours` | `3.0` | Rotation period threshold in hours |
| `geo_signal_threshold` | `3` | Minimum geological signals for jumponium rule |
| `jumponium_materials` | (list) | Material names to check for jumponium synthesis |
| `exotic_star_types` | (list) | Exact StarType codes considered exotic |
| `ggg_planet_classes` | (list) | PlanetClass values considered GGG candidates |
| `nsp_mundane_signal_types` | (list) | FSSSignalDiscovered signal types **not** flagged as NSP |

---

## Parsing quirks

- **Cutoff filter**: every event with `timestamp < expedition_start_timestamp`
  is silently discarded. Set this to the timestamp of your first expedition jump
  to exclude pre-departure activity in the same journal directory.

- **CarrierJump vs FSDJump**: `CarrierJump` events go into a separate table and
  are excluded from jump/distance totals. The carrier can move independently;
  only commander FSD jumps count.

- **Organic scans — 3 stages**: `ScanOrganic` fires for `Log` (approach),
  `Sample` (first sample), and `Analyse` (complete). All 3 rows are stored.
  The "distinct organic variants" metric counts only stage-3 (Analyse) rows
  with a non-null variant.

- **Carto sales — scan-vs-sale timing**: `MultiSellExplorationData` fires when
  you sell at a station. Credits are attributed to the leg active *at sale
  time*, not when the systems were scanned.

- **Idempotent ingestion**: every event is hashed (SHA-256 of normalised JSON)
  and stored in `events_raw` with a UNIQUE constraint. Reprocessing the same
  file is safe. Byte offsets are also tracked per file so backfill skips
  already-processed content on restart.

- **Continued journals**: when a journal file reaches ~15 MB the game creates a
  new file and emits a `Continued` event. The tracker handles this naturally by
  processing all files in chronological order with hash deduplication.

---

## Running unit tests

```
pytest tests/ -v --ignore=tests/test_validate.py
```

The unit tests use in-memory databases and synthetic journal lines — no real
journal files needed.

---

## Resetting / starting a new expedition

When an expedition ends — or if you want to abandon one and start fresh —
clear all accumulated data without touching your route configuration.

**From the config window** (recommended):

Open the configuration window (`python ui/config_window.py` or tray → Configure expedition…),
scroll to the **Reset expedition data** section, and click **Reset data…**.
A confirmation dialog lists exactly what will be deleted.

**From the command line:**

```
python tracker.pyw --reset
```

Type `YES` at the prompt to confirm.

**What is deleted:**

| Item | Deleted? |
|---|---|
| `tracker.db` | Yes — all jump, scan, and organic data |
| `output/` | Yes — all exported xlsx and csv files |
| `validation_baseline.json` | Yes — if present |
| `config.toml` | **No** — your expedition definition is preserved |
| `tracker.log` | **No** |

Stop the tracker (tray → **Stop & exit**) before resetting. The database
cannot be deleted while the tracker process has it open.

After resetting, update `config.toml` with your new expedition route if
needed, then launch the tracker to start fresh.

To reset a different expedition config, pass it: `python tracker.pyw --config
config_hypiae_aim.toml --reset` deletes that config's `db_path`,
`output_dir` contents and `baseline_path` only. A survey CSV is never deleted.
(The config window's reset button always targets `config.toml`.)

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Tray icon doesn't appear | Run `python tracker.pyw --cli` to see error output |
| Wrong jump counts | Check `tracker.log` — look for "Skipping" or "Error handling" lines |
| Waypoint not auto-closing | Confirm exact `StarSystem` string in-game; update `config.toml` |
| `tomllib` import error | You're running Python < 3.11; upgrade or `pip install tomli` |
| Shortcut won't launch | Re-run `make_shortcut.py`; check pythonw.exe path in the output |

---

## How this was built

Built with AI-assisted development. I wrote the requirements, data model, and architecture rules, and directed AI coding assistants to implement them. Every change went through my review, the validation checks, and the pytest suite before release.

---

## Example: Galactic Six Points Expedition

The following documents the expedition this tracker was originally built for,
as a concrete illustration of how the tool is used in practice.

### Background

Elite Dangerous is a space-flight simulator built around a full-scale, 1:1
recreation of our Milky Way galaxy: roughly 400 billion star systems, the
overwhelming majority of which no human player has ever visited. One of the
game's core pursuits is exploration — flying out into uncharted space, scanning
the stars, planets, moons, and lifeforms you find, and being the first
commander to put your name on a new discovery.

Exploration in Elite Dangerous is part science expedition, part personal
odyssey. The science is real: a commander dropping into an untouched system is
the first to chart its stars, measure the mass and chemistry of its worlds, and
document the lifeforms found on them — and your name stays attached to every
body you discover, a permanent entry in humanity's shared map of the galaxy.
The odyssey is the rest of it — weeks alone in the dark, tens of thousands of
light-years from another soul, navigating star to star for the singular thrill
of arriving somewhere no one has ever been.

### The expedition

The Galactic Six Points Expedition is a long-haul voyage organised around six
destination systems — one for each direction a starship can travel in the
galaxy: North, South, East, West, Zenith (up), and Nadir (down). This is not a
quick trip: weeks or months of game time, the survey of thousands of star
systems, and several hundreds of thousands of light-years of travel.

### The Galactic Six Points waypoints

| Label | System |
|---|---|
| Nadir | HD 6428 |
| Zenith | HIP 58832 |
| West | Sphiesi HX-L d7-0 |
| East | Ood Fleau ZJ-I d9-0 |
| South | Lyed YJ-I d9-0 |
| North | Oevasy SG-Y d0 |

Final destination: **Parrot's Head Sector EL-Y d70**
