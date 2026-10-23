"""
Creates a Desktop shortcut (.lnk) pointing to tracker.pyw via pythonw.exe.
Also saves a companion icon (.ico) next to the script: converted from the
repo's icon.png artwork when present, else a generated compass rose.

Run once:
  python make_shortcut.py

For a second expedition config (e.g. a sector survey):
  python make_shortcut.py --config config_hypiae_aim.toml --name "ED Ledger - Hypiae Aim"
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT     = Path(__file__).parent.resolve()
SCRIPT   = ROOT / "tracker.pyw"
ICON     = ROOT / "tracker.ico"
ICON_PNG = ROOT / "icon.png"

_ICO_SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]


def _png_to_ico(png: Path, ico: Path) -> None:
    """Convert square PNG artwork to a multi-size .ico.

    The artwork's rounded frame sits on a solid black background; that
    background is flood-filled to transparent from each corner so the icon
    isn't a black square on the desktop.
    """
    from PIL import Image, ImageDraw

    img = Image.open(png).convert("RGBA")
    w, h = img.size
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if img.getpixel(corner)[3] != 0:
            ImageDraw.floodfill(img, corner, (0, 0, 0, 0), thresh=40)
    img.save(str(ico), format="ICO", sizes=_ICO_SIZES)


def _write_icon() -> None:
    """Save the shortcut icon as an .ico file."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Pillow not installed — skipping icon generation.")
        return

    if ICON_PNG.exists():
        _png_to_ico(ICON_PNG, ICON)
        print(f"Icon converted from {ICON_PNG.name} -> {ICON}")
        return

    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = size // 2
    r = size // 2 - 4

    draw.ellipse([c - r, c - r, c + r, c + r], outline="#4FC3F7", width=2)
    tri_h = r - 6
    tri_w = 7
    draw.polygon([(c, c - tri_h), (c - tri_w, c - 4), (c + tri_w, c - 4)], fill="#1565C0")
    draw.polygon([(c, c + tri_h), (c - tri_w, c + 4), (c + tri_w, c + 4)], fill="#C62828")
    draw.polygon([(c + tri_h, c), (c + 4, c - tri_w), (c + 4, c + tri_w)], fill="#BDBDBD")
    draw.polygon([(c - tri_h, c), (c - 4, c - tri_w), (c - 4, c + tri_w)], fill="#BDBDBD")
    draw.ellipse([c - 3, c - 3, c + 3, c + 3], fill="#FFF176")

    img.save(str(ICON), format="ICO", sizes=[(64, 64), (32, 32), (16, 16)])
    print(f"Icon saved -> {ICON}")


def _find_pythonw() -> str:
    """Return the path to pythonw.exe for the current Python installation."""
    candidate = Path(sys.executable).parent / "pythonw.exe"
    if candidate.exists():
        return str(candidate)
    # Fallback: search PATH
    import shutil
    found = shutil.which("pythonw")
    if found:
        return found
    raise FileNotFoundError(
        "pythonw.exe not found.  Make sure Python is installed with the Windows launcher."
    )


def _get_desktop() -> Path:
    """Return the real Desktop path, respecting OneDrive / shell folder redirection."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        )
        val, _ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        return Path(os.path.expandvars(val))
    except Exception:
        return Path(os.path.expandvars("%USERPROFILE%")) / "Desktop"


def _create_shortcut(pythonw: str, name: str = "ED Expedition Ledger",
                     config: "str | None" = None) -> None:
    desktop = _get_desktop()
    lnk     = desktop / f"{name}.lnk"
    icon_str = str(ICON) if ICON.exists() else ""
    args = f'"{SCRIPT}"' + (f' --config "{(ROOT / config).resolve()}"' if config else "")

    ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{lnk}')
$sc.TargetPath      = '{pythonw}'
$sc.Arguments       = '{args}'
$sc.WorkingDirectory= '{ROOT}'
$sc.Description     = '{name}'
{f"$sc.IconLocation   = '{icon_str}'" if icon_str else ""}
$sc.Save()
Write-Output 'Shortcut created at {lnk}'
""".strip()

    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(result.stdout.strip() or f"Shortcut created → {lnk}")
    else:
        print(f"PowerShell error:\n{result.stderr}")
        sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description="Create a Desktop shortcut for the tracker.")
    ap.add_argument("--config", help="Expedition config file (default: config.toml)")
    ap.add_argument("--name", default="ED Expedition Ledger", help="Shortcut name")
    args = ap.parse_args()

    _write_icon()
    pythonw = _find_pythonw()
    print(f"pythonw.exe -> {pythonw}")
    _create_shortcut(pythonw, args.name, args.config)
    print("Done.  You can now launch the tracker from the Desktop shortcut.")


if __name__ == "__main__":
    main()
