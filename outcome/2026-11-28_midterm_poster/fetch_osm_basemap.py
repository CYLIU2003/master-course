"""Download the OpenStreetMap tiles under the Shibu 21-23 routes and stitch them into one image.

One-off, researcher-approved download (2026-11-11). Tiles: https://tile.openstreetmap.org (zoom 15),
(c) OpenStreetMap contributors, ODbL. The figure that uses the image must carry that credit.
Run from the repository root:
  .venv/Scripts/python.exe outcome/2026-11-28_midterm_poster/fetch_osm_basemap.py
Writes osm_basemap_z15.png and osm_basemap_z15.json (tile range) next to this script.
"""
import io
import json
import math
import time
import urllib.request
from pathlib import Path

import pandas as pd
from PIL import Image

HERE = Path(__file__).parent
Z = 15
routes = pd.read_parquet("data/built/tokyu_full/routes.parquet")
stops = pd.read_parquet("data/built/tokyu_full/stops.parquet").drop_duplicates("id").set_index("id")
ids = {s for seq in routes[routes.routeFamilyCode.isin(["渋21", "渋22", "渋23"])].stopSequence for s in seq if s in stops.index}
lat = stops.loc[list(ids), "lat"].astype(float)
lon = stops.loc[list(ids), "lon"].astype(float)


def tile(lon_, lat_):
    n = 2 ** Z
    return (lon_ + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat_))) / math.pi) / 2 * n


x0, y1 = tile(lon.min() - 0.012, lat.min() - 0.008)
x1, y0 = tile(lon.max() + 0.012, lat.max() + 0.008)
tx0, tx1, ty0, ty1 = int(x0), int(x1), int(y0), int(y1)
count = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
if count > 120:
    raise SystemExit(f"too many tiles: {count}")
canvas = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
for tx in range(tx0, tx1 + 1):
    for ty in range(ty0, ty1 + 1):
        request = urllib.request.Request(f"https://tile.openstreetmap.org/{Z}/{tx}/{ty}.png",
                                         headers={"User-Agent": "route-map-figure/1.0 (one-off academic poster figure)"})
        with urllib.request.urlopen(request, timeout=30) as response:
            canvas.paste(Image.open(io.BytesIO(response.read())).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
        time.sleep(0.25)
canvas.save(HERE / "osm_basemap_z15.png")
(HERE / "osm_basemap_z15.json").write_text(json.dumps({"zoom": Z, "tx0": tx0, "ty0": ty0, "tx1": tx1, "ty1": ty1, "tiles": count,
                                                      "source": "https://tile.openstreetmap.org", "credit": "(c) OpenStreetMap contributors"}), encoding="utf-8")
print("tiles", count, "size", canvas.size)
