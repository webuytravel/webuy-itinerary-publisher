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

# Trip Type, read off the live edit form's el-select on 2026-09-11.
# Same numbers the backend stores in itemType.
TRANSPORT, ACCOMMODATION, ATTRACTION, OTHERS, FOOD, LOCAL_TRANSPORT, GUIDE = (
    1, 2, 3, 4, 5, 6, 7)

# The form offers exactly six highlight rows and has no "add row" control.
# Six is the house layout, not a limit (UPLOAD_RUNBOOK 第 5 步第 4 条): four
# headline sights/experiences, one `·`-compressed secondary line, one on food.
HOUSE_HIGHLIGHTS = {
    "ACKMG12T": [
        ("Panda Train · Tianfu Express — a Song-spirited rail journey across "
         "Sichuan and Yunnan, in 2+1 land first-class",
         "熊猫专列·锦绣天府号 —— 宋韵雅致的川滇旅列，2+1 陆地头等舱"),
        ("Tiger Leaping Gorge, where the Jinsha River gathers force between "
         "sheer mountain walls",
         "虎跳峡，金沙江激流穿行嶙峋峡谷，山河气势磅礴"),
        ("Shangri-La by choice: Pudacuo National Park, or Ganden Sumtseling — "
         "the “Little Potala Palace” of northwest Yunnan",
         "香格里拉二选一：普达措国家公园，或“小布达拉宫”噶丹·松赞林寺"),
        ("Tengchong by choice: the steaming valley of Rehai Hot Spring Park, "
         "or a hike into the Gaoligong Mountains",
         "腾冲二选一：云雾氤氲的热海公园，或高黎贡山秘境徒步"),
        ("Qionghai Lake · Jianchang Ancient City · Dukezong Ancient Town · "
         "Dadi Tea Estate · Jietou Village · Qiluo Ancient Town",
         "邛海 · 建昌古城 · 独克宗古城 · 大地茶海 · 界头村 · 绮罗古镇"),
        ("Traditional fisherman's banquet · an 800-year camellia-oil feast at "
         "Hemu · caravan tea on the Tea Horse Road",
         "特色渔家宴 · 和睦茶花村八百年茶油宴 · 茶马古道马帮茶"),
    ],
}

# Meals actually provided each day, read off the brochure's per-day footer.
# 424's convention is a plain slash-joined list of the meals included, with "-"
# on a day that includes none — not a description of what was eaten.
MEALS = {
    "ACKMG12T": {
        1:  ("-", "-"),
        2:  ("Breakfast / Dinner", "早餐 / 晚餐"),
        3:  ("Breakfast / Dinner", "早餐 / 晚餐"),
        4:  ("Breakfast / Lunch / Dinner", "早餐 / 午餐 / 晚餐"),
        5:  ("Breakfast / Lunch / Dinner", "早餐 / 午餐 / 晚餐"),
        6:  ("Breakfast / Lunch / Dinner", "早餐 / 午餐 / 晚餐"),
        7:  ("Breakfast / Lunch / Dinner", "早餐 / 午餐 / 晚餐"),
        8:  ("Breakfast / Lunch / Dinner", "早餐 / 午餐 / 晚餐"),
        9:  ("Breakfast / Lunch / Dinner", "早餐 / 午餐 / 晚餐"),
        10: ("Breakfast / Lunch / Dinner", "早餐 / 午餐 / 晚餐"),
        11: ("Breakfast / Lunch", "早餐 / 午餐"),
        12: ("Breakfast", "早餐"),
    },
}

# Trip Type per item, keyed (day, sortNum within the day).
# Anything not listed is an Attraction, which is what 16 of 424's 17 items are.
TRIP_TYPES = {
    "ACKMG12T": {
        (1, 0): TRANSPORT,      # fly SIN -> CTU, private transfer
        (2, 0): TRANSPORT,      # board the train
        (3, 0): OTHERS,         # welcome ceremony, on board
        (3, 1): OTHERS,         # cultural salon, on board
        (4, 2): FOOD,           # fisherman's banquet
        (10, 2): FOOD,          # caravan tea
        (11, 0): OTHERS,        # closing programme on board
        (12, 0): TRANSPORT,     # private transfer, fly home
    },
}


def build(code: str, itinerary: dict, defaults: dict) -> dict:
    if code not in HOUSE_HIGHLIGHTS:
        raise SystemExit(
            f"{code}: no HOUSE_HIGHLIGHTS entry. The form has six highlight "
            f"rows and they are an editorial decision — write them before "
            f"uploading, don't let the brochure's 15-22 bullets through raw.")
    meals = MEALS[code]
    types = TRIP_TYPES.get(code, {})

    sections = []
    for s in itinerary["sections"]:
        day = s["day"]
        if day not in meals:
            raise SystemExit(f"{code}: no MEALS entry for day {day}")
        meal_en, meal_zh = meals[day]
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
        for n, (en, zh) in enumerate(HOUSE_HIGHLIGHTS[code])
    ]

    # Echo the prefill's departures back with ifshow=1. The form ticks them all
    # on Tour Type selection; the prefill hands them over at 0. Prices come from
    # the prefill untouched — this tool does not invent a fare.
    tours = []
    for t in defaults.get("tourList") or []:
        t = json.loads(json.dumps(t))
        t["ifshow"] = 1
        tours.append(t)
    if not tours:
        raise SystemExit(
            f"{code}: the prefill carries no departures. wt_travel cannot exist "
            f"before wt_tour — editTravel answers 500 'tourId Cannot be empty'. "
            f"Ops has to open the departures first.")

    name = itinerary["product_name"]
    for v in name.values():
        if "&" in v:
            raise SystemExit(f"{code}: product name contains '&' — use 'and'.")

    return {
        "id": None,
        "tourTypeId": defaults.get("tourTypeId") or itinerary.get("tour_type_id"),
        "tourTypeCode": defaults.get("tourTypeCode") or code,
        "tourTypeName": defaults.get("tourTypeName"),
        "paxType": defaults.get("paxType"),
        "productName": name["en"],
        "productNameCn": name["zh"],
        "travelStatus": 0,          # 0 = UnPublished. Going live stays human.
        "region": defaults.get("region") or "CHN",
        "sellingPrice": defaults.get("sellingPrice"),
        "startingPrice": defaults.get("startingPrice") or 0,
        "minPassager": defaults.get("minPassager") or 0,
        "validPeriod": defaults.get("validPeriod") or "",
        "videoUrl": None,
        "videoCoverUrl": None,
        "routeMapUrl": None,
        "flightInfo": defaults.get("flightInfo"),
        "highlightsList": highlights,
        "sectionList": sections,
        "thumbneilList": [],
        "desktopImageList": [],
        "mobileImageList": [],
        "priceList": defaults.get("priceList") or [],
        "tourList": tours,
        "packageInclusive": defaults.get("packageInclusive"),
        "packageRemarks": defaults.get("packageRemarks"),
        "importantNote": defaults.get("importantNote"),
        "packageInclusiveCn": defaults.get("packageInclusiveCn"),
        "packageRemarksCn": defaults.get("packageRemarksCn"),
        "importantNoteCn": defaults.get("importantNoteCn"),
        **{f"tag{n}": defaults.get(f"tag{n}") for n in range(1, 7)},
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

    payload = build(args.code, itinerary, defaults)

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
    print(f"  departures   : {len(payload['tourList'])} (ifshow=1)",
          file=sys.stderr)
    print(f"  images       : none — the image pipeline runs separately and has "
          f"its own sign-off gate", file=sys.stderr)


if __name__ == "__main__":
    main()
