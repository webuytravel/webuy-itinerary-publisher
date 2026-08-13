#!/usr/bin/env python3
"""Re-fetch stock picks at full resolution and re-encode the crops from them.

`photo_source` saves whatever the search API hands back, and both stock APIs
hand back a *preview*: Pexels at `?w=940&h=650`, Unsplash at `&w=1080`. Those
are display sizes for a results grid, not masters. Everything downstream then
inherits the ceiling — WBCHET's carousel sources are all 940×627, which is a
1.72× upscale into the landscape slot and 2.30× into the portrait one, past
the 2.0 the house standard allows.

Both URLs carry their own size as a query parameter, so the same photograph is
one request away at full size. Nothing about the *selection* changes: same
photo, same crop rules, same order — only the pixels underneath.

Re-crops rather than re-scales, because the crop window is chosen by detail
density and a bigger source can support a better window, not just a sharper
one. Only writes when the new source is genuinely larger.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from lib.image_norm import normalise
from lib.image_spec import CAROUSEL, CAROUSEL_MOBILE, SECTION, THUMBNAIL, crop_window

SLOTS = {"carousel": CAROUSEL, "thumbnail": THUMBNAIL, "section": SECTION}
UA = {"User-Agent": "Mozilla/5.0 (webuy-itinerary-publisher)"}


def full_size(url: str) -> str | None:
    """Rewrite a stock preview URL to ask for the master."""
    if "images.pexels.com" in url:
        # Pexels serves the original when no resize params are attached.
        return url.split("?")[0]
    if "images.unsplash.com" in url:
        # Unsplash keeps its signature in ixid; only w/q may be raised.
        out = re.sub(r"([?&])w=\d+", r"\g<1>w=2400", url)
        return out if out != url else url + "&w=2400"
    return None


def fetch(url: str, dest: Path) -> Path | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            dest.write_bytes(r.read())
    except Exception as exc:  # noqa: BLE001 — report and carry on
        print(f"    fetch failed: {exc}")
        return None
    return dest


def size(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        return im.size


def run(code: str, work: Path, assets_root: Path) -> None:
    plan_path = work / code / "plan.json"
    plan = json.loads(plan_path.read_text("utf-8"))
    hi_dir = work / code / "cand_hi"
    improved = 0

    for placement in plan["placements"]:
        slot = placement["slot"]
        if slot not in SLOTS:
            continue
        url = full_size(placement.get("source_ref", "") or "")
        if not url:
            continue

        old = assets_root / placement["src_path"]
        if not old.exists():
            old = Path(placement["src_path"])
        if not old.exists():
            continue

        name = Path(placement["src_path"]).name
        new = fetch(url, hi_dir / name)
        if not new:
            continue

        try:
            ow, oh = size(old)
            nw, nh = size(new)
        except Exception:  # noqa: BLE001 — a truncated download is not fatal
            continue
        if nw <= ow:
            continue

        spec = SLOTS[slot]
        out = assets_root / placement["out_path"]
        before = spec.width / crop_window(ow, oh, spec.aspect)[0]
        result = normalise(new, out, spec)
        placement["src_path"] = str(new)
        placement["bytes"] = result.bytes
        placement["upscale"] = result.upscale
        # `materialise` stamped the pre-swap ratio into the note, and the
        # review page prints the note verbatim next to the tag it derives
        # from `upscale`. Leaving it stale makes the page contradict itself
        # — "放大 0.35×" beside "upscaled 2.04×" — right where a human is
        # being asked to judge whether a picture is sharp enough to ship.
        placement["note"] = re.sub(r"\s*\|?\s*upscaled [\d.]+×", "",
                                   placement.get("note", "")).strip(" |")
        if result.upscale > 1.0:
            placement["note"] = (placement["note"]
                                 + f" | upscaled {result.upscale:.2f}×").strip(" |")
        improved += 1
        print(f"  {slot} {placement['position']}: {ow}x{oh} -> {nw}x{nh} | "
              f"upscale {before:.2f}x -> {result.upscale:.2f}x")

        if slot == "carousel":
            mob = work / code / "out_mobile" / f"carousel_{placement['position']:02d}_mobile.jpg"
            m = normalise(new, mob, CAROUSEL_MOBILE)
            print(f"      mobile -> {m.upscale:.2f}x")

    if improved:
        plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), "utf-8")
    print(f"{code}: {improved} images re-encoded from full-size sources")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*")
    ap.add_argument("--work", type=Path, default=Path("work"))
    ap.add_argument("--assets-root", type=Path, default=Path("."))
    args = ap.parse_args()
    for code in args.codes or ["WBCKWE", "WBCURC", "WBCHET"]:
        print(f"== {code}")
        run(code, args.work, args.assets_root)


if __name__ == "__main__":
    main()
