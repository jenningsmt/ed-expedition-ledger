"""
Galactic region lookup from system coordinates.

The journal only carries a Region on CodexEntry events, which don't fire in
every system, so the survey tracker derives region from FSDJump StarPos
instead.  Region indices match the game's $Codex_RegionName_NN; names are
adjusted to the game's Region_Localised spelling where the map differs.

Lookup algorithm and data vendored from klightspeed/EliteDangerousRegionMap:

    MIT License

    Copyright (c) 2020 Ben Peddell

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
"""
from __future__ import annotations

from .regionmap_data import regions, regionmap

_X0 = -49985
_Z0 = -24105

# Map spelling → in-game Region_Localised spelling (verified against journals).
_GAME_NAMES = {
    31: "The Formidine Rift",
}


def find_region(x: float, y: float, z: float) -> "tuple[int, str] | None":
    """Return (region_id, region_name) for galactic coordinates, or None if
    the point lies outside the region map.  y is unused: regions are columns."""
    px = int((x - _X0) * 83 / 4096)
    pz = int((z - _Z0) * 83 / 4096)
    if px < 0 or pz < 0 or pz >= len(regionmap):
        return None

    rx = 0
    for run_len, pv in regionmap[pz]:
        if px < rx + run_len:
            break
        rx += run_len
    else:
        pv = 0

    if pv == 0:
        return None
    return pv, _GAME_NAMES.get(pv, regions[pv])
