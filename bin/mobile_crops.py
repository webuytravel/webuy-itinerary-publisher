#!/usr/bin/env python3
"""Materialise the portrait half of the carousel into `work/<CODE>/out_mobile/`.

The Skybear carousel is two independent slots, and the create form marks both
required: Desktop Display Image (landscape) and Mobile Display Image
(portrait). `bin/compose.py` only ever produced the landscape set, so
`out_mobile/` existed but stayed empty and the phone slot had nothing to feed.

This re-crops from each placement's **original source**, never from the
finished 4:3 JPEG — `image_spec.CAROUSEL_MOBILE` says so in as many words, and
the reason is visible the moment you try it: re-cropping a 4:3 frame to 3:4
keeps a 810×1080 sliver of a 1440×1080 image and throws away most of what the
photo was chosen for.

Selection is not re-decided here. The same photos in the same carousel order
get a second crop, so whatever was signed off on the review page is what ships
to both slots.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.image_norm import normalise
from lib.image_spec import CAROUSEL_MOBILE


def run(code: str, work: Path, assets_root: Path) -> list[dict]:
    plan = json.loads((work / code / "plan.json").read_text("utf-8"))
    out_dir = work / code / "out_mobile"
    rows = []

    carousel = sorted((p for p in plan["placements"] if p["slot"] == "carousel"),
                      key=lambda p: p["position"])
    for placement in carousel:
        src = assets_root / placement["src_path"]
        if not src.exists():
            raise SystemExit(f"{code}: missing source {src}")
        dest = out_dir / f"carousel_{placement['position']:02d}_mobile.jpg"
        result = normalise(src, dest, CAROUSEL_MOBILE)
        rows.append({
            "pos": placement["position"],
            "path": str(dest.resolve()),
            "bytes": result.bytes,
            "upscale": result.upscale,
            "soft": result.is_soft,
            "subject": placement["subject"],
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*")
    ap.add_argument("--work", type=Path, default=Path("work"))
    ap.add_argument("--assets-root", type=Path, default=Path("."),
                    help="checkout holding the downloaded sources (cand/, cat/, raw/)")
    args = ap.parse_args()

    for code in args.codes or ["WBCKWE", "WBCURC", "WBCHET"]:
        rows = run(code, args.work, args.assets_root)
        soft = [r for r in rows if r["soft"]]
        print(f"{code}: {len(rows)} portrait crops"
              + (f" | {len(soft)} soft (max {max(r['upscale'] for r in soft):.2f}×)"
                 if soft else ""))


if __name__ == "__main__":
    main()
