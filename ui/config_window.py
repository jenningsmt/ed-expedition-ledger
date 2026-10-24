"""
Expedition configuration editor.

Stand-alone:
    python ui/config_window.py [config.toml]
    python tracker.pyw --configure [--config config.toml]
    EDLedger.exe --configure

Launched from the tracker tray (Configure expedition…), and on first run of
the installed app when no config exists yet.
"""
from __future__ import annotations

import re
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import paths

CONFIG_PATH = paths.default_config_path()
RARITY_DEFAULTS = Path(__file__).resolve().parent.parent / "engine" / "rarity_defaults.toml"

_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
)
MODES = {"waypoints": "Waypoint expedition", "sector": "Sector survey"}


# ── TOML serialisation ────────────────────────────────────────────────────────

def _toml_str(value: str) -> str:
    """Serialise a Python string as a TOML literal-string (single quotes) when
    possible, falling back to a basic-string (double quotes) otherwise."""
    if "'" not in value:
        return f"'{value}'"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_list(values: "list[str]") -> str:
    return "[" + ", ".join(_toml_str(v) for v in values) + "]"


def _rarity_block(path: Path) -> str:
    """Everything from the [rarity] table onwards in the current file, else
    the bundled defaults."""
    for source in (path, RARITY_DEFAULTS):
        if source.exists():
            text = source.read_text(encoding="utf-8")
            m = re.search(r"^\[rarity\]", text, re.MULTILINE)
            if m:
                return text[m.start():]
    return ""


def _write_config(path: Path, data: dict) -> None:
    """Write the config.  data holds every top-level key to keep; mode decides
    whether waypoints or a [survey] block is written."""
    rarity = _rarity_block(path)
    sector_mode = data["mode"] == "sector"

    lines = [
        "# ED Expedition Ledger",
        "# Edit with the configuration window (tray → Configure expedition…).",
        "",
        "# ── Journal source ────────────────────────────────────────────────────────────",
        f"journal_dir = {_toml_str(data['journal_dir'])}",
        "",
        "# ── Output & database ─────────────────────────────────────────────────────────",
        f"output_dir    = {_toml_str(data['output_dir'])}",
        f"db_path       = {_toml_str(data['db_path'])}",
        f"baseline_path = {_toml_str(data['baseline_path'])}",
        "",
        "# ── Commanders ────────────────────────────────────────────────────────────────",
        "# Every CMDR whose journals count toward this expedition.",
        f"commanders = {_toml_list(data['commanders'])}",
        "",
        "# ── Expedition definition ─────────────────────────────────────────────────────",
        "# 'waypoints': legs close at waypoints.  'sector': a sector survey.",
        f"mode = {_toml_str(data['mode'])}",
    ]
    if sector_mode:
        lines.append(f"sector = {_toml_str(data['sector'])}")
    lines += [
        "",
        "# Events before this UTC time (YYYY-MM-DDTHH:MM:SSZ) are ignored.",
        f"expedition_start_timestamp = {_toml_str(data['expedition_start_timestamp'])}",
        f"expedition_start_system    = {_toml_str(data['expedition_start_system'])}",
    ]
    if not sector_mode:
        lines += [
            "",
            "# Arriving here closes the final leg and marks the expedition complete.",
            f"expedition_end_system = {_toml_str(data['expedition_end_system'])}",
        ]
        if "waypoints_only_export" in data:
            wo = "true" if data["waypoints_only_export"] else "false"
            lines.append(f"waypoints_only_export = {wo}")
        lines += [
            "",
            "# ── Waypoints ─────────────────────────────────────────────────────────────────",
            "# One [[waypoints]] block per destination. Visited in any order.",
            "# Jumping AWAY from an unvisited waypoint closes the current leg.",
            "",
        ]
        for wp in data["waypoints"]:
            lines += [
                "[[waypoints]]",
                f"label  = {_toml_str(wp['label'])}",
                f"system = {_toml_str(wp['system'])}",
                "",
            ]
    else:
        survey = data["survey"]
        lines += [
            "",
            "# ── Sector survey candidate list ──────────────────────────────────────────────",
            "[survey]",
            f"csv_path = {_toml_str(survey['csv_path'])}",
        ]
        if survey["regions"]:
            lines.append(f"regions  = {_toml_list(survey['regions'])}")
        lines += [
            f"region_complete_when = {_toml_str(survey['region_complete_when'])}",
            "",
        ]

    body = "\n".join(lines) + "\n"
    if rarity:
        body += (
            "# ── Rare / notable first-discovery detector ──────────────────────────────────\n"
            + rarity
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ── Config window ─────────────────────────────────────────────────────────────

class ConfigWindow:
    def __init__(self, config_path: Path = CONFIG_PATH, first_run: bool = False) -> None:
        self._config_path = Path(config_path)
        self._first_run = first_run
        self._raw: dict = {}            # loaded config, for keys the window doesn't edit
        self._wp_rows: list[dict] = []  # [{frame, label_var, system_var}]
        self.saved = False

        self.root = tk.Tk()
        self.root.title("ED Expedition Ledger — Expedition Configuration")
        self.root.resizable(False, True)
        self.root.minsize(660, 400)

        style = ttk.Style(self.root)
        style.theme_use("clam")

        self._build_ui()
        self._load_config()
        self._on_mode_change()

        # Centre on screen
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = (self.root.winfo_screenwidth()  - w) // 2
        y = max(0, (self.root.winfo_screenheight() - h) // 2)
        self.root.geometry(f"+{x}+{y}")

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 6}

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        if self._first_run:
            ttk.Label(
                outer, foreground="gray", justify=tk.LEFT,
                text=("Welcome to ED Expedition Ledger. Set up your expedition, then "
                      "click Save — the tracker starts in the system tray."),
            ).pack(fill=tk.X, padx=12, pady=(0, 4))

        self._build_commander_section(outer).pack(fill=tk.X, **pad)
        self._build_route_section(outer).pack(fill=tk.X, **pad)

        # Mode-specific section is swapped in here.
        self._mode_holder = ttk.Frame(outer)
        self._mode_holder.pack(fill=tk.BOTH, expand=True)
        self._waypoints_frame = self._build_waypoints_section(self._mode_holder)
        self._sector_frame    = self._build_sector_section(self._mode_holder)

        self._build_storage_section(outer).pack(fill=tk.X, **pad)
        self._build_data_section(outer).pack(fill=tk.X, **pad)
        self._build_buttons(outer).pack(fill=tk.X, padx=12, pady=(0, 12))

    def _build_commander_section(self, parent: ttk.Frame) -> ttk.LabelFrame:
        lf = ttk.LabelFrame(parent, text="Commanders & Journals", padding=8)

        self._commanders_var = tk.StringVar()
        self._journal_dir_var = tk.StringVar()

        self._field_row(lf, "Commanders", self._commanders_var, row=0)
        ttk.Label(lf, text="One or more CMDR names, comma-separated", foreground="gray").grid(
            row=1, column=1, sticky=tk.W, padx=(8, 0), pady=(0, 2))

        ttk.Label(lf, text="Journal dir").grid(row=2, column=0, sticky=tk.W, pady=3)
        jd_entry = ttk.Entry(lf, textvariable=self._journal_dir_var, width=48)
        jd_entry.grid(row=2, column=1, sticky=tk.EW, padx=(8, 4), pady=3)
        ttk.Button(lf, text="Browse…", width=8,
                   command=self._browse_journal_dir).grid(row=2, column=2, pady=3)

        lf.columnconfigure(1, weight=1)
        return lf

    def _build_route_section(self, parent: ttk.Frame) -> ttk.LabelFrame:
        lf = ttk.LabelFrame(parent, text="Expedition", padding=8)

        self._mode_var         = tk.StringVar(value="waypoints")
        self._start_system_var = tk.StringVar()
        self._end_system_var   = tk.StringVar()
        self._start_ts_var     = tk.StringVar()

        ttk.Label(lf, text="Type").grid(row=0, column=0, sticky=tk.W, pady=3)
        modes = ttk.Frame(lf)
        modes.grid(row=0, column=1, columnspan=2, sticky=tk.W, padx=(8, 0), pady=3)
        for value, text in MODES.items():
            ttk.Radiobutton(modes, text=text, value=value, variable=self._mode_var,
                            command=self._on_mode_change).pack(side=tk.LEFT, padx=(0, 16))

        self._field_row(lf, "Start system",      self._start_system_var, row=1)
        self._field_row(lf, "Start timestamp",   self._start_ts_var,     row=2)
        hint = "UTC · format: YYYY-MM-DDTHH:MM:SSZ · journal events before this are ignored"
        ttk.Label(lf, text=hint, foreground="gray").grid(
            row=3, column=1, sticky=tk.W, padx=(8, 0), pady=(0, 2)
        )
        self._end_label = ttk.Label(lf, text="Final destination")
        self._end_label.grid(row=4, column=0, sticky=tk.W, pady=3)
        self._end_entry = ttk.Entry(lf, textvariable=self._end_system_var, width=52)
        self._end_entry.grid(row=4, column=1, columnspan=2, sticky=tk.EW, padx=(8, 0), pady=3)

        lf.columnconfigure(1, weight=1)
        return lf

    def _build_waypoints_section(self, parent: ttk.Frame) -> ttk.LabelFrame:
        lf = ttk.LabelFrame(parent, text="Waypoints", padding=8)

        # Column headers
        hdr = ttk.Frame(lf)
        ttk.Label(hdr, text="Label",  width=20, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(hdr, text="System", width=32, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 4))
        hdr.pack(fill=tk.X, padx=(0, 24))  # 24 = width of remove button column

        ttk.Separator(lf, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(2, 4))

        # Scrollable rows area
        container = ttk.Frame(lf)
        container.pack(fill=tk.BOTH, expand=True)

        self._wp_canvas = tk.Canvas(container, highlightthickness=0, height=180)
        sb = ttk.Scrollbar(container, orient=tk.VERTICAL,
                           command=self._wp_canvas.yview)
        self._wp_canvas.configure(yscrollcommand=sb.set)

        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._wp_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._wp_inner = ttk.Frame(self._wp_canvas)
        self._wp_canvas_win = self._wp_canvas.create_window(
            (0, 0), window=self._wp_inner, anchor=tk.NW
        )

        self._wp_inner.bind("<Configure>", self._on_wp_frame_resize)
        self._wp_canvas.bind("<Configure>", self._on_canvas_resize)

        # Mousewheel scrolling
        self._wp_canvas.bind("<Enter>",  self._bind_mousewheel)
        self._wp_canvas.bind("<Leave>",  self._unbind_mousewheel)

        # Add button
        ttk.Button(lf, text="+ Add waypoint",
                   command=self._add_waypoint_row).pack(anchor=tk.W, pady=(6, 0))

        return lf

    def _build_sector_section(self, parent: ttk.Frame) -> ttk.LabelFrame:
        lf = ttk.LabelFrame(parent, text="Sector survey", padding=8)

        self._sector_var   = tk.StringVar()
        self._csv_var      = tk.StringVar()
        self._regions_var  = tk.StringVar()
        self._complete_var = tk.StringVar(value="completed")
        self._csv_info_var = tk.StringVar()
        self._csv_info: dict | None = None

        self._field_row(lf, "Sector", self._sector_var, row=0)

        ttk.Label(lf, text="Candidate CSV").grid(row=1, column=0, sticky=tk.W, pady=3)
        ttk.Entry(lf, textvariable=self._csv_var, width=48).grid(
            row=1, column=1, sticky=tk.EW, padx=(8, 4), pady=3)
        ttk.Button(lf, text="Browse…", width=8,
                   command=self._browse_csv).grid(row=1, column=2, pady=3)
        ttk.Label(lf, textvariable=self._csv_info_var, foreground="gray").grid(
            row=2, column=1, columnspan=2, sticky=tk.W, padx=(8, 0), pady=(0, 2))
        self._csv_var.trace_add("write", lambda *_: self._inspect_csv())

        ttk.Label(lf, text="Claimed regions").grid(row=3, column=0, sticky=tk.W, pady=3)
        ttk.Entry(lf, textvariable=self._regions_var, width=48).grid(
            row=3, column=1, sticky=tk.EW, padx=(8, 4), pady=3)
        ttk.Button(lf, text="All", width=8,
                   command=self._claim_all_regions).grid(row=3, column=2, pady=3)
        ttk.Label(lf, foreground="gray",
                  text="Clustered files only · e.g. R14, R22 · blank = every region in the file").grid(
            row=4, column=1, columnspan=2, sticky=tk.W, padx=(8, 0), pady=(0, 2))

        ttk.Label(lf, text="Region complete when").grid(row=5, column=0, sticky=tk.W, pady=3)
        cw = ttk.Frame(lf)
        cw.grid(row=5, column=1, columnspan=2, sticky=tk.W, padx=(8, 0), pady=3)
        ttk.Radiobutton(cw, text="every candidate has a full FSS (or a resolution)",
                        value="completed", variable=self._complete_var).pack(anchor=tk.W)
        ttk.Radiobutton(cw, text="every candidate has been visited (or has a resolution)",
                        value="visited", variable=self._complete_var).pack(anchor=tk.W)

        lf.columnconfigure(1, weight=1)
        return lf

    def _build_storage_section(self, parent: ttk.Frame) -> ttk.LabelFrame:
        lf = ttk.LabelFrame(parent, text="Exports", padding=8)
        self._output_var = tk.StringVar()
        ttk.Label(lf, text="Output folder").grid(row=0, column=0, sticky=tk.W, pady=3)
        ttk.Entry(lf, textvariable=self._output_var, width=48).grid(
            row=0, column=1, sticky=tk.EW, padx=(8, 4), pady=3)
        ttk.Button(lf, text="Browse…", width=8,
                   command=self._browse_output).grid(row=0, column=2, pady=3)
        lf.columnconfigure(1, weight=1)
        return lf

    def _build_data_section(self, parent: ttk.Frame) -> ttk.LabelFrame:
        lf = ttk.LabelFrame(parent, text="Legs & data", padding=8)
        ttk.Label(
            lf,
            text=("Close current leg: end the open leg under a name you choose and\n"
                  "export it (works while the tracker runs).\n"
                  "Reset: delete this expedition's database, exports and baseline\n"
                  "(stop the tracker first). The config and survey CSV are kept."),
            foreground="gray",
            justify=tk.LEFT,
        ).pack(side=tk.LEFT, padx=(0, 16))
        buttons = ttk.Frame(lf)
        buttons.pack(side=tk.RIGHT, anchor=tk.E)
        ttk.Button(buttons, text="Close current leg…",
                   command=self._close_leg).pack(fill=tk.X, pady=(0, 4))
        ttk.Button(buttons, text="Reset data…",
                   command=self._confirm_reset).pack(fill=tk.X)
        return lf

    def _build_buttons(self, parent: ttk.Frame) -> ttk.Frame:
        row = ttk.Frame(parent)
        ttk.Button(row, text="Save",   width=10, command=self._save).pack(side=tk.RIGHT, padx=4)
        ttk.Button(row, text="Cancel", width=10, command=self.root.destroy).pack(side=tk.RIGHT)
        ttk.Label(row, text=str(self._config_path), foreground="gray").pack(side=tk.LEFT)
        return row

    def _on_mode_change(self) -> None:
        sector = self._mode_var.get() == "sector"
        self._waypoints_frame.pack_forget()
        self._sector_frame.pack_forget()
        frame = self._sector_frame if sector else self._waypoints_frame
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        if sector:
            self._end_label.grid_remove()
            self._end_entry.grid_remove()
        else:
            self._end_label.grid()
            self._end_entry.grid()

    # ── Waypoint row management ───────────────────────────────────────────────

    def _add_waypoint_row(self, label: str = "", system: str = "") -> None:
        label_var  = tk.StringVar(value=label)
        system_var = tk.StringVar(value=system)

        row_frame = ttk.Frame(self._wp_inner)
        row_frame.pack(fill=tk.X, pady=1)

        ttk.Entry(row_frame, textvariable=label_var,  width=20).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(row_frame, textvariable=system_var, width=32).pack(side=tk.LEFT, padx=(0, 4))

        entry = {"frame": row_frame, "label_var": label_var, "system_var": system_var}

        remove_btn = ttk.Button(
            row_frame, text="×", width=3,
            command=lambda e=entry: self._remove_waypoint_row(e),
        )
        remove_btn.pack(side=tk.LEFT)

        self._wp_rows.append(entry)
        self._scroll_to_bottom()

    def _remove_waypoint_row(self, entry: dict) -> None:
        entry["frame"].destroy()
        self._wp_rows.remove(entry)

    # ── Canvas / scroll helpers ───────────────────────────────────────────────

    def _on_wp_frame_resize(self, event: tk.Event) -> None:
        self._wp_canvas.configure(scrollregion=self._wp_canvas.bbox("all"))

    def _on_canvas_resize(self, event: tk.Event) -> None:
        self._wp_canvas.itemconfig(self._wp_canvas_win, width=event.width)

    def _scroll_to_bottom(self) -> None:
        self.root.update_idletasks()
        self._wp_canvas.yview_moveto(1.0)

    def _bind_mousewheel(self, _: tk.Event) -> None:
        self._wp_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _: tk.Event) -> None:
        self._wp_canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event: tk.Event) -> None:
        self._wp_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ── Field helper ──────────────────────────────────────────────────────────

    def _field_row(self, parent: ttk.Frame, label: str,
                   var: tk.StringVar, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=3)
        ttk.Entry(parent, textvariable=var, width=52).grid(
            row=row, column=1, columnspan=2, sticky=tk.EW, padx=(8, 0), pady=3
        )

    # ── Browse ────────────────────────────────────────────────────────────────

    def _browse_journal_dir(self) -> None:
        current = self._journal_dir_var.get()
        chosen = filedialog.askdirectory(
            title="Select Elite Dangerous journal folder",
            initialdir=current if current else None,
        )
        if chosen:
            self._journal_dir_var.set(chosen)

    def _browse_csv(self) -> None:
        current = self._csv_var.get().strip()
        chosen = filedialog.askopenfilename(
            title="Select a Sector Surveyor candidate CSV",
            initialdir=str(Path(current).parent) if current else None,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if chosen:
            self._csv_var.set(str(Path(chosen)))

    def _browse_output(self) -> None:
        current = self._output_var.get().strip()
        chosen = filedialog.askdirectory(
            title="Select the export folder",
            initialdir=current if current and Path(current).is_dir() else None,
        )
        if chosen:
            self._output_var.set(str(Path(chosen)))

    # ── Candidate CSV ─────────────────────────────────────────────────────────

    def _inspect_csv(self) -> None:
        from engine.survey import SurveyFormatError, inspect_candidates
        self._csv_info = None
        path = self._csv_var.get().strip()
        if not path:
            self._csv_info_var.set("")
            return
        try:
            info = inspect_candidates(self._resolve(path))
        except FileNotFoundError:
            self._csv_info_var.set("File not found.")
            return
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            msg = str(exc) if isinstance(exc, SurveyFormatError) else f"Can't read file: {exc}"
            self._csv_info_var.set(msg[:110] + ("…" if len(msg) > 110 else ""))
            return
        self._csv_info = info
        if info["format"] == "clustered":
            regions = info["regions"]
            span = f"{regions[0]}–{regions[-1]}" if len(regions) > 1 else ", ".join(regions)
            self._csv_info_var.set(
                f"Clustered file · {info['rows']:,} candidates · "
                f"{len(regions)} survey region(s): {span}")
        else:
            self._csv_info_var.set(f"Plain candidate list · {info['rows']:,} candidates · no survey regions")

    def _claim_all_regions(self) -> None:
        if self._csv_info and self._csv_info["regions"]:
            self._regions_var.set(", ".join(self._csv_info["regions"]))

    def _resolve(self, path: str) -> Path:
        """Paths in the config are relative to the config file's folder."""
        p = Path(path).expanduser()
        return p if p.is_absolute() else self._config_path.parent / p

    @staticmethod
    def _split(text: str) -> "list[str]":
        return [t.strip() for t in text.replace(";", ",").split(",") if t.strip()]

    # ── Load ──────────────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        storage = paths.default_storage()
        if not self._config_path.exists():
            journal = paths.default_journal_dir()
            self._journal_dir_var.set(journal if Path(journal).is_dir() else "")
            self._output_var.set(storage["output_dir"])
            return

        import tomllib
        with open(self._config_path, "rb") as fh:
            raw = tomllib.load(fh)
        self._raw = raw

        commanders = raw.get("commanders") or ([raw["commander"]] if raw.get("commander") else [])
        self._commanders_var.set(", ".join(commanders))
        self._journal_dir_var.set(raw.get("journal_dir", ""))
        self._mode_var.set(raw.get("mode", "waypoints"))
        self._start_system_var.set(raw.get("expedition_start_system", ""))
        self._end_system_var.set(raw.get("expedition_end_system", ""))
        self._start_ts_var.set(raw.get("expedition_start_timestamp", ""))
        self._output_var.set(raw.get("output_dir", storage["output_dir"]))

        for wp in raw.get("waypoints", []):
            self._add_waypoint_row(wp.get("label", ""), wp.get("system", ""))

        self._sector_var.set(raw.get("sector", ""))
        survey = raw.get("survey") or {}
        self._csv_var.set(survey.get("csv_path", ""))
        self._regions_var.set(", ".join(survey.get("regions", [])))
        self._complete_var.set(survey.get("region_complete_when", "completed"))

    # ── Save ──────────────────────────────────────────────────────────────────

    def _collect(self) -> dict:
        storage = paths.default_storage()
        data = {
            "journal_dir":               self._journal_dir_var.get().strip(),
            "output_dir":                self._output_var.get().strip(),
            "db_path":                   self._raw.get("db_path", storage["db_path"]),
            "baseline_path":             self._raw.get("baseline_path", storage["baseline_path"]),
            "commanders":                self._split(self._commanders_var.get()),
            "mode":                      self._mode_var.get(),
            "sector":                    self._sector_var.get().strip(),
            "expedition_start_timestamp": self._start_ts_var.get().strip(),
            "expedition_start_system":   self._start_system_var.get().strip(),
            "expedition_end_system":     self._end_system_var.get().strip(),
            "waypoints": [
                {
                    "label":  r["label_var"].get().strip(),
                    "system": r["system_var"].get().strip(),
                }
                for r in self._wp_rows
            ],
            "survey": {
                "csv_path":             self._csv_var.get().strip(),
                "regions":              [r.upper() for r in self._split(self._regions_var.get())],
                "region_complete_when": self._complete_var.get(),
            },
        }
        if "waypoints_only_export" in self._raw:
            data["waypoints_only_export"] = bool(self._raw["waypoints_only_export"])
        return data

    def _save(self) -> None:
        errors = self._validate()
        if errors:
            messagebox.showerror(
                "Validation errors",
                "\n".join(f"• {e}" for e in errors),
                parent=self.root,
            )
            return

        try:
            _write_config(self._config_path, self._collect())
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self.root)
            return

        self.saved = True
        follow_up = ("The tracker will now start in the system tray."
                     if self._first_run else
                     "Restart the tracker (tray → Stop & exit, then launch it again) "
                     "for changes to take effect.")
        messagebox.showinfo(
            "Saved", f"Config saved to:\n{self._config_path}\n\n{follow_up}",
            parent=self.root,
        )
        self.root.destroy()

    # ── Legs & data ───────────────────────────────────────────────────────────

    def _load_saved_cfg(self) -> "dict | None":
        if not self._config_path.exists():
            messagebox.showinfo("Save first", "Save the configuration first.", parent=self.root)
            return None
        from engine.config import load as load_cfg
        try:
            return load_cfg(self._config_path)
        except Exception as exc:
            messagebox.showerror("Config error", str(exc), parent=self.root)
            return None

    def _close_leg(self) -> None:
        cfg = self._load_saved_cfg()
        if cfg is None:
            return
        if not Path(cfg["db_path"]).exists():
            messagebox.showinfo("Nothing to close",
                                "The tracker hasn't recorded anything yet.", parent=self.root)
            return

        from engine.db       import Database
        from engine.exporter import export_for_config
        from engine.legs     import LegManager
        from engine.survey   import make_survey

        db = Database(cfg["db_path"])
        try:
            leg = db.get_active_leg()
            if leg is None:
                messagebox.showinfo("Nothing to close", "There is no open leg.", parent=self.root)
                return
            default = (f"{cfg['sector']} (pre-regions)" if cfg.get("mode") == "sector"
                       else f"Leg {leg['ordinal']} (manual)")
            name = simpledialog.askstring(
                "Close current leg",
                f"Leg {leg['ordinal']} started {leg['start_ts']}.\n\n"
                "Close it under this name and export it?",
                initialvalue=default, parent=self.root,
            )
            if not name or not name.strip():
                return
            closed_id = LegManager(db, cfg).manual_close(label=name.strip())
            try:
                xlsx = export_for_config(cfg, db, closed_id, survey=make_survey(cfg)).name
            except Exception as exc:
                xlsx = f"(export failed: {exc})"
            messagebox.showinfo(
                "Leg closed",
                f"Leg {leg['ordinal']} closed as '{name.strip()}' and exported:\n{xlsx}\n\n"
                f"Leg {leg['ordinal'] + 1} is now open.",
                parent=self.root,
            )
        finally:
            db.close()

    def _confirm_reset(self) -> None:
        cfg = self._load_saved_cfg()
        if cfg is None:
            return
        db_path, output_dir, baseline = (
            Path(cfg["db_path"]), Path(cfg["output_dir"]), Path(cfg["baseline_path"]))
        confirmed = messagebox.askokcancel(
            "Reset expedition data",
            "This will permanently delete:\n\n"
            f"  • {db_path}\n"
            f"  • everything in {output_dir}\n"
            f"  • {baseline.name}\n\n"
            "The config and any survey CSV will NOT be changed.\n\n"
            "Stop the tracker (tray → Stop & exit) before resetting.\n\n"
            "Continue?",
            parent=self.root,
        )
        if not confirmed:
            return

        from engine.reset import reset_expedition_data
        try:
            removed = reset_expedition_data(paths.ROOT, db_path, output_dir, baseline)
        except OSError as exc:
            messagebox.showerror(
                "Reset failed",
                f"{exc}\n\nIf the tracker is running, stop it first.",
                parent=self.root,
            )
            return

        parts = []
        if removed["db"]:
            parts.append(f"{db_path.name} deleted")
        if removed["exports"]:
            parts.append(f"{removed['exports']} export file(s) deleted")
        if removed["baseline"]:
            parts.append(f"{baseline.name} deleted")

        msg = "\n".join(f"  • {p}" for p in parts) if parts else "  Nothing to delete."
        messagebox.showinfo(
            "Reset complete",
            f"Expedition data cleared:\n\n{msg}\n\n"
            "Launch the tracker to start fresh.",
            parent=self.root,
        )

    def _validate(self) -> list[str]:
        errors: list[str] = []
        sector = self._mode_var.get() == "sector"

        if not self._split(self._commanders_var.get()):
            errors.append("At least one commander name is required.")

        if not self._journal_dir_var.get().strip():
            errors.append("Journal directory is required.")
        elif not Path(self._journal_dir_var.get().strip()).is_dir():
            errors.append("Journal directory does not exist.")

        ts = self._start_ts_var.get().strip()
        if not ts:
            errors.append("Start timestamp is required.")
        elif not _TS_RE.match(ts):
            errors.append("Start timestamp must be in format YYYY-MM-DDTHH:MM:SSZ.")

        if not self._output_var.get().strip():
            errors.append("Output folder is required.")

        if sector:
            if not self._sector_var.get().strip():
                errors.append("Sector name is required.")
            if self._csv_var.get().strip():
                self._inspect_csv()
                if self._csv_info is None:
                    errors.append(f"Candidate CSV: {self._csv_info_var.get() or 'unusable file.'}")
                else:
                    claimed = [r.upper() for r in self._split(self._regions_var.get())]
                    if claimed and self._csv_info["format"] != "clustered":
                        errors.append("Claimed regions need a clustered candidate file.")
                    unknown = [r for r in claimed if r not in self._csv_info["regions"]]
                    if unknown and self._csv_info["format"] == "clustered":
                        errors.append(f"Not in the candidate file: {', '.join(unknown)}")
        else:
            if not self._end_system_var.get().strip():
                errors.append("Final destination system is required.")
            for i, row in enumerate(self._wp_rows, 1):
                if not row["label_var"].get().strip():
                    errors.append(f"Waypoint {i}: label is required.")
                if not row["system_var"].get().strip():
                    errors.append(f"Waypoint {i}: system name is required.")

        return errors

    def run(self) -> bool:
        """Show the window; returns True if the config was saved."""
        self.root.mainloop()
        return self.saved


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ConfigWindow(Path(sys.argv[1]) if len(sys.argv) > 1 else CONFIG_PATH).run()
