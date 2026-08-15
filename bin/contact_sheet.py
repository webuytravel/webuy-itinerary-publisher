#!/usr/bin/env python3
"""Build per-day contact sheets so a person can look at every candidate.

The pipeline has two axes and only one of them is arithmetic. `image_appeal`
scores colour locally and for free, but `docs/DESIGN.md` 6.7 is a list of
things no arithmetic catches: the right subject in the wrong country, a
museum model instead of the building, a night light show that does not match
the brochure's tone. Those need eyes, and eyes need the pictures laid out
next to each other with their block name and their numbers attached.

One sheet per day, one row per block, candidates left to right — ③ Commons
first (GPS-checked, duller) then ④ stock (no GPS, brighter), because that is
the order the trade-off runs in. Each tile is captioned
`<source><n> s<saturation>` and tiles below the house floor
(`image_appeal.MIN_SATURATION`) get a red bar, so "this whole block is grey"
is visible without reading a single number.

    python3 bin/contact_sheet.py WBLJG9
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.image_appeal import MIN_SATURATION, measure

WORK = Path("work")

# Tiles have to be big enough to answer "is this really that place?". At
# 300px in a single unwrapped row the day-6 sheet came out 3898px wide and
# every tile rendered at ~150px — enough to see "a mountain", not enough to
# see *which* mountain. Wrapping at 6 keeps the sheet within a readable
# width so the tiles survive downscaling.
TILE_W, TILE_H = 420, 280
CAPTION_H = 26
LABEL_W = 250          # left gutter holding the block name
PAD = 4
COLS = 6               # candidates per row before wrapping


def rows_for(code: str) -> dict[int, list[tuple[str, list[dict]]]]:
    """`{day: [(block, [candidate, ...]), ...]}` merging ③ and ④."""
    base = WORK / code
    commons, stock = {}, {}
    if (base / "commons.json").exists():
        commons = json.loads((base / "commons.json").read_text("utf-8"))
    if (base / "candidates.json").exists():
        stock = json.loads((base / "candidates.json").read_text("utf-8"))

    days: dict[int, list] = {}
    for block in sorted(set(commons) | set(stock)):
        merged = []
        for tag, table in (("C", commons), ("S", stock)):
            entry = table.get(block) or {}
            for row in entry.get("candidates", []):
                merged.append({**row, "tag": tag})
        day = (commons.get(block) or stock.get(block) or {}).get("day", 0)
        days.setdefault(day, []).append((block, merged))
    return days


def build_day(code: str, day: int, blocks: list, out: Path) -> Path | None:
    if not any(c for _, c in blocks):
        return None
    strips = [(block, (len(c) + COLS - 1) // COLS or 1) for block, c in blocks]
    W = LABEL_W + min(COLS, max((len(c) for _, c in blocks), default=1)) * (TILE_W + PAD)
    row_h = TILE_H + CAPTION_H + PAD
    H = sum(n for _, n in strips) * row_h
    sheet = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(sheet)

    y0 = 0
    for (block, cands), (_, nrows) in zip(blocks, strips):
        draw.text((6, y0 + 8), f"D{day}", fill="black")
        draw.text((6, y0 + 24), block[4:][:34], fill="black")
        draw.text((6, y0 + 40), f"{len(cands)} cand", fill="#666")
        for c, row in enumerate(cands):
            x = LABEL_W + (c % COLS) * (TILE_W + PAD)
            y = y0 + (c // COLS) * row_h
            try:
                with Image.open(row["path"]) as im:
                    im = im.convert("RGB")
                    im.thumbnail((TILE_W, TILE_H))
                    sheet.paste(im, (x + (TILE_W - im.width) // 2, y))
            except Exception:                                  # noqa: BLE001
                draw.rectangle([x, y, x + TILE_W, y + TILE_H], fill="#eee")
                draw.text((x + 8, y + 8), "unreadable", fill="red")
                continue
            appeal = measure(row["path"])
            sat = appeal.saturation if appeal else 0.0
            dull = appeal is None or sat < MIN_SATURATION
            cy = y + TILE_H
            draw.rectangle([x, cy, x + TILE_W, cy + CAPTION_H],
                           fill="#c00" if dull else "#111")
            draw.text((x + 5, cy + 6),
                      f"{row['tag']}{row['n']} {row.get('source','')[:8]} s{sat:.3f}",
                      fill="white")
        y0 += nrows * row_h
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=88)
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    code = argv[1]
    days = rows_for(code)
    for day, blocks in sorted(days.items()):
        out = WORK / code / "sheets" / f"day{day:02d}.jpg"
        made = build_day(code, day, blocks, out)
        if made:
            n = sum(len(c) for _, c in blocks)
            print(f"  D{day}: {len(blocks)} block(s), {n} candidates → {made}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
