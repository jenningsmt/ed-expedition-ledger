"""
Expedition data reset.

Removes tracker.db, all files in output/, and validation_baseline.json (or
the db_path / output_dir / baseline_path of another config).  The config file
is intentionally preserved so the expedition definition can be reused or
updated for a new run.  A survey CSV is never touched.
"""
from __future__ import annotations

import shutil
from pathlib import Path


def reset_expedition_data(
    root: Path,
    db_path: "Path | None" = None,
    output_dir: "Path | None" = None,
    baseline_path: "Path | None" = None,
) -> dict[str, int]:
    """
    Delete all expedition data under root (or at the given config paths).
    Returns counts of what was removed.

    Raises OSError if any file is locked (e.g. tracker.db held open by a
    running tracker process).
    """
    removed: dict[str, int] = {"db": 0, "exports": 0, "baseline": 0}

    db_path = db_path or root / "tracker.db"
    if db_path.exists():
        db_path.unlink()
        removed["db"] = 1

    # Also remove WAL and SHM sidecar files if present
    for suffix in ("-wal", "-shm"):
        p = db_path.with_name(db_path.name + suffix)
        if p.exists():
            p.unlink()

    output_dir = output_dir or root / "output"
    if output_dir.is_dir():
        for child in list(output_dir.iterdir()):
            if child.is_file():
                child.unlink()
            else:
                shutil.rmtree(child)
            removed["exports"] += 1

    baseline = baseline_path or root / "validation_baseline.json"
    if baseline.exists():
        baseline.unlink()
        removed["baseline"] = 1

    return removed
