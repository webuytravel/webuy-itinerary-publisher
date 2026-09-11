#!/usr/bin/env python3
"""Fold an itinerary and its image plan into the one blob the form filler eats.

`work/<CODE>/form_payload.json` is what gets injected into the Skybear admin
page: the text side comes straight from `itinerary.json`, the image side is
`plan.json`'s placements regrouped by slot.

Images are carried as **absolute local paths**, not URLs. The first cut of this
file pointed at `http://127.0.0.1:8777/...` on the theory that a loopback origin
is exempt from mixed-content blocking. It is not, at least not for `fetch`:
called from the https admin page the promise neither resolves nor rejects and
the console stays clean, so the failure looks like a hang rather than a block.
Paths let the upload go through the extension's file input instead, which never
touches the page's network stack.

The crops themselves live under `work/<CODE>/out/` and are gitignored, so they
only exist in a checkout that has actually run `bin/compose.py`. `--assets-root`
points at that checkout when this runs from a worktree.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import editorial

SLOTS = ("carousel", "carousel_mobile", "thumbnail", "route_map", "section",
         "trip")

# Trip Type is a required el-select on every trip item, and the itinerary has
# no such field — the brochures describe what you see, not how it is filed.
# The vocabulary is Skybear's, fixed at seven values; only two of them ever
# apply to a landmark card, and the split is whether the day's entry is a
# place you stop at or a leg you travel. Everything that is not a movement is
# an attraction, which is the safe direction to be wrong in: a mislabelled
# attraction is invisible on the page, a mislabelled transfer is not.
_TRANSPORT = re.compile(
    r"\b(arrival|arrive|depart|departure|homeward|transfer|airport|flight|"
    r"on to|back to|onward|bound|coach to|return to|travel to|drive to)\b", re.I)
_FOOD = re.compile(r"\b(banquet|dinner|lunch|breakfast|tasting|cuisine)\b", re.I)
_STAY = re.compile(r"\b(check[- ]?in|hotel|resort|overnight)\b", re.I)


# The Highlight block is exactly six bilingual rows. Not a form limitation to
# work around — six is the house format. `webuytravel.sg/tours/115`, the direct
# style peer of this batch, publishes exactly six (read live 2026-08-13), laid
# out as four headline lines then two cuisine lines packed with "·":
#
#     Xiaoqikong and Mount Fanjing, both UNESCO World Heritage sites
#     Huangguoshu Waterfall, Asia's largest waterfall
#     Explore geological wonders at Maling River Canyon, Wanfenglin, ...
#     Enjoy a complimentary Miao costume experience
#     Qian Cuisine · Sour Soup Fish · Canyon Flavors · Miao Cuisine
#     Wild Mushroom Cuisine · Long Table Banquet · Grilled Fish Specialty
#
# The itineraries carry 15–22 highlights, one per city plus one per dish, which
# is the right shape for a brochure and the wrong shape for this block. Folding
# them is an editorial call: the per-dish lines collapse into the two cuisine
# rows losing nothing, and the per-city lines are ranked by draw, so what falls
# off the end is the weakest. The meal-count and hotel-grade lines are dropped
# because the reference page does not carry them — meals already appear on every
# day of the itinerary.
#
# 成品六条连同取舍理由在 `work/<CODE>/editorial.json` 的 `highlights` 里
# (issue #4;`notes.highlights` 记着册子原来列了几条、落掉的是哪几条)。


def trip_type(title: str) -> str:
    # Only the opening words decide. A movement card leads with the movement
    # ("Coach to Nalati", "Homeward Bound"); when the phrase turns up later the
    # card is about something else and merely ends by going somewhere —
    # "Optional Desert Activities and Return to Ordos" is a desert afternoon,
    # not a transfer, and filing it under Transportation would hide it.
    if _TRANSPORT.search(" ".join(title.split()[:3])):
        return "Transportation"
    if _STAY.search(title):
        return "Accommodation"
    if _FOOD.search(title):
        return "Food"
    return "Attractions"


def build(code: str, work: Path, assets_root: Path) -> dict:
    base = work / code
    itinerary = json.loads((base / "itinerary.json").read_text("utf-8"))
    plan = json.loads((base / "plan.json").read_text("utf-8"))
    doc = editorial.load(code, work)

    images: dict[str, list[dict]] = {slot: [] for slot in SLOTS}
    missing = []
    for placement in plan["placements"]:
        out = placement.get("out_path")
        if not out:
            continue
        path = (assets_root / out).resolve()
        if not path.exists():
            missing.append(str(path))
        row = {
            "pos": placement["position"],
            "path": str(path),
            "bytes": placement.get("bytes"),
            "subject": placement["subject"],
        }
        # trip 图的地址是 (天, 第几张景点卡) —— 光有 pos 到这一层就不唯一了,
        # 上传端要靠 trip_index 找到对应的那张卡。
        if placement["slot"] == "trip":
            row["trip_index"] = placement.get("trip_index") or 0
        images.setdefault(placement["slot"], []).append(row)
    # The portrait carousel is produced by `bin/mobile_crops.py` and is not in
    # the plan — it is the same picks at a second ratio, matched by position.
    for row in images["carousel"]:
        mobile = work / code / "out_mobile" / f"carousel_{row['pos']:02d}_mobile.jpg"
        if mobile.exists():
            images["carousel_mobile"].append({
                "pos": row["pos"],
                "path": str(mobile.resolve()),
                "bytes": mobile.stat().st_size,
                "subject": row["subject"],
            })
        else:
            missing.append(str(mobile))

    for rows in images.values():
        rows.sort(key=lambda r: r["pos"])

    if missing:
        # Loud on purpose: a payload that silently points at absent crops would
        # only surface as an upload that quietly attaches nothing.
        raise SystemExit(f"{code}: {len(missing)} crops missing, first={missing[0]}")

    for section in itinerary["sections"]:
        for item in section.get("trip_items", []):
            item["trip_type"] = trip_type(item["title"]["en"])

    return {
        "type_code": itinerary["type_code"],
        "travel_days": itinerary.get("travel_days"),
        "product_name": itinerary["product_name"],
        "highlights": [{"en": en, "zh": zh}
                       for en, zh in editorial.highlights(code, doc)],
        "highlights_source": itinerary["highlights"],
        "sections": itinerary["sections"],
        "images": images,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*", default=["WBCKWE", "WBCURC", "WBCHET"])
    ap.add_argument("--work", type=Path, default=Path("work"))
    ap.add_argument("--assets-root", type=Path, default=Path("."),
                    help="checkout that holds the materialised work/<CODE>/out/ crops")
    args = ap.parse_args()

    for code in args.codes or ["WBCKWE", "WBCURC", "WBCHET"]:
        payload = build(code, args.work, args.assets_root)
        dest = args.work / code / "form_payload.json"
        dest.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
        counts = " ".join(f"{s}={len(payload['images'].get(s, []))}" for s in SLOTS)
        print(f"{code}: sections={len(payload['sections'])} "
              f"highlights={len(payload['highlights'])} | {counts}")


if __name__ == "__main__":
    main()
