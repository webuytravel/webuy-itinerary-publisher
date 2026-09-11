#!/usr/bin/env python3
"""Turn work/<CODE>/itinerary.json into the body `travelMgmt/editTravel` wants.

This is the API counterpart of `bin/make_payload.py`, which builds the blob that
`lib/form_filler.js` types into the Vue form. Same inputs, different target: the
form path depends on `lib/selectors.yaml` matching a bundle that gets rebuilt
without notice, while the backend contract has not moved since the 408 batch —
the 2026-09 redeploy left `VUE_APP_BASE_API` exactly where it was.

The shape below was not guessed. It is `travelMgmt/queryDefaultDataByTourTypeId`
(the prefill the form itself starts from) with the populated field shapes copied
off a real record read back through `travelMgmt/selectVoById` (product 424,
built by this project in August).

Usage:
    python3 bin/make_api_payload.py ACKMG12T --defaults work/ACKMG12T/defaults.json

`--defaults` is the saved response of queryDefaultDataByTourTypeId for this
tour type. It carries `tourList` — the departures, already priced — which we
must echo back untouched apart from `ifshow`. Building that list by hand would
mean inventing prices, so we refuse to run without it.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import editorial
from lib.editorial import ITEM_TYPES

# Trip Type, read off the live edit form's el-select on 2026-09-11. Same numbers
# the backend stores in itemType; the names are what `editorial.json` writes.
ATTRACTION = ITEM_TYPES["ATTRACTION"]

# 这个文件里三张 per-product 的表(六条 highlights、逐日餐食、逐条 Trip Type)
# 都搬到了 `work/<CODE>/editorial.json`(issue #4):
#   highlights  六行房子版式,不是表单限制(UPLOAD_RUNBOOK 第 5 步第 4 条):
#               四条头部景点/体验 + 一条 `·` 压缩的次级景点 + 一条餐食。
#   meals       册子逐日页脚抄下来的。424 的写法是把当天含的餐用 / 连起来,
#               一餐都不含的写 "-",不是描述吃了什么。
#   trip_types  键是「天:当天第几条」,没列出来的一律 Attraction —— 424 的
#               17 条里有 16 条就是 Attraction。


def build(code: str, itinerary: dict, defaults: dict, doc: dict) -> dict:
    highlight_rows = editorial.highlights(code, doc)
    meals = doc.get("meals") or {}
    if not meals:
        raise SystemExit(f"{code}: editorial.json 里没有 meals —— "
                         f"逐日餐食是从册子页脚抄的,上传前要先写")
    types = {tuple(int(x) for x in key.split(":")): ITEM_TYPES[name]
             for key, name in (doc.get("trip_types") or {}).items()}

    sections = []
    for s in itinerary["sections"]:
        day = s["day"]
        if str(day) not in meals:
            raise SystemExit(f"{code}: editorial.json meals 里没有第 {day} 天")
        meal_en, meal_zh = meals[str(day)]["en"], meals[str(day)]["zh"]
        items = []
        for n, it in enumerate(s["trip_items"]):
            items.append({
                "id": None,
                "itemTitle": it["title"]["en"],
                "itemTitleCn": it["title"]["zh"],
                "itemDescription": it["description"]["en"],
                "itemDescriptionCn": it["description"]["zh"],
                "itemType": types.get((day, n), ATTRACTION),
                "sortNum": n,
                "imageList": [],
            })
        sections.append({
            "id": None,
            "sectionName": s["name"]["en"],
            "sectionNameCn": s["name"]["zh"],
            "sectionTitle": s["title"]["en"],
            "sectionTitleCn": s["title"]["zh"],
            "sectionLocation": s["location"]["en"],
            "sectionLocationCn": s["location"]["zh"],
            "sectionDescription": meal_en,
            "sectionDescriptionCn": meal_zh,
            "sortNum": day - 1,
            "imageList": [],
            "itemList": items,
        })

    highlights = [
        {"highlights": en, "highlightsCn": zh, "sortNum": n}
        for n, (en, zh) in enumerate(highlight_rows)
    ]

    # Departures. `editTravel` wants **`tourIdList`** — a flat list of ids —
    # not the rich `tourList` the prefill hands back. Sending the rich list
    # gets `500 tourId Cannot be empty`, which reads like "there are no
    # departures" and sent the first attempt looking for missing wt_tour rows;
    # there were four, in the payload, under the wrong key. The admin's own
    # submit handler is the authority here:
    #     i.tourIdList = (tourList||[]).filter(t => t.checked).map(t => t.tourId)
    # Everything the prefill carries per departure (prices, inventory) is the
    # wt_tour's own data — the backend reads it from there, so we only name them.
    tour_ids = [t["tourId"] for t in (defaults.get("tourList") or []) if t.get("tourId")]
    if not tour_ids:
        raise SystemExit(
            f"{code}: the prefill carries no departures. wt_travel cannot exist "
            f"before wt_tour — editTravel answers 500 'tourId Cannot be empty'. "
            f"Ops has to open the departures first.")

    name = itinerary["product_name"]
    for v in name.values():
        if "&" in v:
            raise SystemExit(f"{code}: product name contains '&' — use 'and'.")

    # The field set below mirrors the admin's own submit handler exactly, down
    # to `id: ""` rather than null. The prefill response carries more keys than
    # that (region, paxType, sellingPrice, priceList, validPeriod, …) — those
    # are display data the form reads and never sends back, because they live
    # on the wt_tour / tour type rows. Echoing them is at best ignored and at
    # worst confuses the write, so they stay out.
    #
    # minPassager / startingPrice / tag1..6 are omitted on purpose: the form
    # only attaches them when paxType is 2 or 8 (FIT-style products). This one
    # is paxType 1 (G-Group Tour).
    return {
        "id": "",
        "tourTypeId": defaults.get("tourTypeId") or itinerary.get("tour_type_id"),
        "productName": name["en"],
        "productNameCn": name["zh"],
        "travelStatus": 0,          # 0 = UnPublished. Going live stays human.
        "flightInfo": defaults.get("flightInfo") or "",
        "highlightsList": highlights,
        "sectionList": sections,
        "thumbneilList": [],        # plain URL strings, not image objects
        "desktopImageList": [],
        "mobileImageList": [],
        "routeMapUrl": "",
        "videoUrl": "",
        "videoCoverUrl": "",
        "tourIdList": tour_ids,
        "packageInclusive": defaults.get("packageInclusive") or "",
        "packageRemarks": defaults.get("packageRemarks") or "",
        "importantNote": defaults.get("importantNote") or "",
        "packageInclusiveCn": defaults.get("packageInclusiveCn") or "",
        "packageRemarksCn": defaults.get("packageRemarksCn") or "",
        "importantNoteCn": defaults.get("importantNoteCn") or "",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("--work", type=Path, default=Path("work"))
    ap.add_argument("--defaults", type=Path, required=True,
                    help="saved queryDefaultDataByTourTypeId response")
    args = ap.parse_args()

    base = args.work / args.code
    itinerary = json.loads((base / "itinerary.json").read_text())

    raw = json.loads(args.defaults.read_text())
    defaults = raw.get("data", raw)

    payload = build(args.code, itinerary, defaults,
                    editorial.load(args.code, args.work))

    out = base / "api_payload.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    print(f"wrote {out}", file=sys.stderr)
    print(f"  travelStatus : {payload['travelStatus']} (0 = UnPublished)",
          file=sys.stderr)
    print(f"  sections     : {len(payload['sectionList'])}", file=sys.stderr)
    print(f"  trip items   : "
          f"{sum(len(s['itemList']) for s in payload['sectionList'])}",
          file=sys.stderr)
    print(f"  highlights   : {len(payload['highlightsList'])}", file=sys.stderr)
    print(f"  departures   : {len(payload['tourIdList'])} (tourIdList)",
          file=sys.stderr)
    print(f"  images       : none — the image pipeline runs separately and has "
          f"its own sign-off gate", file=sys.stderr)


if __name__ == "__main__":
    main()
