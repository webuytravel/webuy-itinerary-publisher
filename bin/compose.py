#!/usr/bin/env python3
"""Turn an itinerary + the three image sources into a reviewable image plan.

Runs the slot assignment the review page is built from. The ordering of the
sources is the whole point, and it is not arbitrary:

1. **The brochure's own photos.** The product team chose them, so they beat
   anything found later on intent. Small, though, and the deck templates
   leave furniture behind — everything is gated in `pdf_images`.
2. **Webuy's own catalogue.** Photos already published on `webuytravel.sg`
   for a sibling product: licensed, in house style, correctly sized, and
   labelled by the CMS rather than by a designer's caption layer.
3. **Stock**, already fetched into `work/<code>/candidates.json` and already
   looked at — this script never decides whether a photo depicts what it
   claims, because nothing here can see. It only places what was approved.

Matching is on tokens shared between a day's `photo_subject` and a source
image's label, which works because both name the same landmark in the same
two languages. `OVERRIDES` exists for the cases where that is not enough and
a human (or a multimodal pass) has already made the call.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.catalogue_source import CatalogueImage, fetch as fetch_catalogue
from lib.image_plan import Gap, ImagePlan, Placement, dedupe, materialise
from lib.preview import render

WORK = Path("work")

# Tokens that carry no discriminating power — every other landmark has them.
STOP = {
    "the", "and", "of", "a", "an", "in", "at", "on", "to", "for", "with",
    "includes", "incl", "eco", "friendly", "shuttle", "round", "trip",
    "cart", "china", "scenic", "area", "tour", "visit", "experience",
    "special", "free", "time", "optional", "view", "drive", "along",
}


def tokens(text: str) -> set[str]:
    """Latin words plus CJK bigrams — so 黄果树大瀑布 matches 黄果树瀑布."""
    lowered = text.lower()
    words = {w for w in re.findall(r"[a-z]{3,}", lowered) if w not in STOP}
    han = re.findall(r"[一-鿿]+", lowered)
    for run in han:
        words |= {run[i:i + 2] for i in range(len(run) - 1)}
    return words


def score(subject: str, label: str) -> float:
    """Shared-token overlap, normalised by the shorter side.

    Normalising by the shorter side matters because catalogue alt text
    carries trailing inclusions — "Wanfenglin (Ten Thousand Peaks Forest)
    (includes eco-cart)" — that would otherwise dilute a perfect match.
    """
    a, b = tokens(subject), tokens(label)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


MATCH_FLOOR = 0.34  # below this, a "match" is coincidental token overlap


def load(code: str) -> dict:
    base = WORK / code
    out = {"itinerary": json.loads((base / "itinerary.json").read_text("utf-8"))}
    subjects = json.loads((WORK / "pdf_subjects.json").read_text("utf-8"))
    raw = json.loads((base / "pdf_images.json").read_text("utf-8"))
    by_ref = {f"p{i['page']}#{i['index']}": i for i in raw}
    # only images a human looked at and called real; generic/CGI-suspect are
    # deliberately excluded rather than silently ranked lower
    out["pdf"] = [
        {**by_ref[s["ref"]], "subject": s["subject"], "verdict": s["verdict"]}
        for s in subjects.get(code, [])
        if s["ref"] in by_ref and s["verdict"] in ("real", "asset")
    ]
    cand = base / "candidates.json"
    out["stock"] = json.loads(cand.read_text("utf-8")) if cand.exists() else {}
    return out


def catalogue_for(code: str, tours: list[str]) -> list[dict]:
    cat = json.loads((WORK / "catalogue.json").read_text("utf-8"))
    rows = []
    for tour in tours:
        for image_id, alt in cat.get(tour, []):
            rows.append({"image_id": image_id, "alt": alt, "tour": tour})
    return rows


def pull_catalogue(code: str, rows: list[dict]) -> None:
    """Download the ones we intend to use. OSS originals, no resize chain."""
    dest_dir = WORK / code / "cat"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        dest = dest_dir / f"{row['image_id']}.jpg"
        if not dest.exists():
            fetch_catalogue(CatalogueImage(row["image_id"], row["alt"],
                                           row["tour"]), dest)
        row["path"] = str(dest)


def compose(code: str, region: str, tours: list[str], overrides: dict) -> ImagePlan:
    data = load(code)
    cat_rows = catalogue_for(code, tours)
    plan = ImagePlan(type_code=code, region=region)

    used_pdf, used_cat, chosen_cat = set(), set(), []

    for section in data["itinerary"]["sections"]:
        day = section["day"]
        subjects = [t["photo_subject"] for t in section.get("trip_items", [])
                    if t.get("photo_subject")]
        key = f"d{day:02d}"

        # Explicit picks come first. Stock is never auto-selected: the
        # search ranks by relevance to a *query*, not by whether the photo
        # is of the right place, and the launch probe proved the gap —
        # "Yingxian Wooden Pagoda" put the Xi'an Big Wild Goose Pagoda at
        # #1 and the correct building at #5. Every entry below is one a
        # multimodal pass looked at and approved.
        for kind, ref, note in overrides.get(key, []):
            if kind == "stock":
                block, n = ref
                row = next((c for c in data["stock"].get(block, {}).get("candidates", [])
                            if c["n"] == n), None)
                if row:
                    plan.placements.append(Placement(
                        slot="section", position=day, origin="web",
                        subject=data["stock"][block]["subject"],
                        source_ref=row["url"], src_path=row["path"],
                        credit=row["source"], note=note))
            elif kind == "file":
                plan.placements.append(Placement(
                    slot="section", position=day, origin="web",
                    subject=note, source_ref=ref, src_path=ref,
                    credit="Wikimedia Commons", license="CC BY-SA 4.0",
                    note=note))
        if key in overrides:
            continue

        placed = 0
        for subject in subjects:
            if placed >= 2:  # two photos a day keeps the page from sprawling
                break
            best_pdf = max(
                ((i, score(subject, i["subject"])) for i in data["pdf"]
                 if i["kind"] == "photo" and i["path"] not in used_pdf),
                key=lambda t: t[1], default=(None, 0.0))
            best_cat = max(
                ((r, score(subject, r["alt"])) for r in cat_rows
                 if r["image_id"] not in used_cat),
                key=lambda t: t[1], default=(None, 0.0))

            if best_pdf[1] >= MATCH_FLOOR and best_pdf[1] >= best_cat[1]:
                img = best_pdf[0]
                used_pdf.add(img["path"])
                plan.placements.append(Placement(
                    slot="section", position=day, origin="pdf",
                    subject=img["subject"],
                    source_ref=f"p{img['page']} #{img['index']}",
                    src_path=img["path"], credit="brochure"))
                placed += 1
            elif best_cat[1] >= MATCH_FLOOR:
                row = best_cat[0]
                used_cat.add(row["image_id"])
                chosen_cat.append(row)
                plan.placements.append(Placement(
                    slot="section", position=day, origin="catalogue",
                    subject=row["alt"], source_ref=row["tour"],
                    src_path="", credit="webuytravel.sg"))
                placed += 1

        if placed == 0 and subjects:
            plan.gaps.append(Gap(slot="section", position=day,
                                 subjects=subjects,
                                 reason="no source matched this day"))

    pull_catalogue(code, chosen_cat)
    for placement in plan.placements:
        if placement.origin == "catalogue" and not placement.src_path:
            row = next(r for r in chosen_cat if r["alt"] == placement.subject)
            placement.src_path = row["path"]

    # Route map: the brochure's own diagram, never cropped.
    route = next((i for i in data["pdf"] if i["kind"] == "route_map"), None)
    if route:
        plan.placements.append(Placement(
            slot="route_map", position=0, origin="pdf",
            subject="itinerary route map",
            source_ref=f"p{route['page']} #{route['index']}",
            src_path=route["path"], credit="brochure",
            note="brochure schematic — uploaded as-is"))

    return plan


def fill_carousel(plan: ImagePlan, code: str, tours: list[str], target: int = 8):
    """Refill the carousel from what no day used.

    Sections win contested images: a day with no picture of the thing it
    sells is a worse page than a carousel one slide shorter, and the
    carousel can always be refilled from the leftovers — the reverse is not
    true.
    """
    used = {p.src_path for p in plan.placements}
    pool = []
    for row in catalogue_for(code, tours):
        path = WORK / code / "cat" / f"{row['image_id']}.jpg"
        if str(path) not in used:
            pool.append(row)
    picks = pool[:target]
    pull_catalogue(code, picks)
    for i, row in enumerate(picks):
        plan.placements.append(Placement(
            slot="carousel", position=i, origin="catalogue",
            subject=row["alt"], source_ref=row["tour"],
            src_path=row["path"], credit="webuytravel.sg",
            note="hero" if i == 0 else ""))

    if not picks:
        # No sibling product is published for this region, so there is no
        # leftover pool. Reprise the day photos rather than ship a one-slide
        # carousel — `dedupe(cross_slot=False)` is built for exactly this and
        # still removes repeats within a slot.
        for i, src in enumerate([p for p in plan.of("section")][:target]):
            plan.placements.append(Placement(
                slot="carousel", position=i, origin=src.origin,
                subject=src.subject, source_ref=src.source_ref,
                src_path=src.src_path, credit=src.credit,
                license=src.license,
                note=("hero | " if i == 0 else "") + "复用当日配图(该区域无在售同类产品可采)"))

    hero = next((p for p in plan.of("carousel") if p.position == 0), None)
    if hero:
        plan.placements.append(Placement(
            slot="thumbnail", position=0, origin=hero.origin,
            subject=hero.subject, source_ref=hero.source_ref,
            src_path=hero.src_path, credit=hero.credit, license=hero.license))


# Days the token matcher cannot resolve, each already decided by looking.
# WBCHET day 4 and day 7 follow the rule the Planner set on 2026-08-12: where
# no photograph of the landmark exists that is actually of that place, show a
# compliant picture of the day's city or region instead of a lookalike from
# somewhere else. Stock returned real ice caves (Siberia) and real volcanoes
# (Etna, Nicaragua) — right subject, wrong continent, and a page selling this
# trip cannot carry them.
# Every entry here is a picture a multimodal pass looked at and approved,
# with the reason it beat the alternatives. Stock is never auto-picked.
#
# WBCHET days 4 and 7 follow the rule the Planner set on 2026-08-12: where no
# photograph of the landmark exists that is actually of that place, show a
# compliant picture of the day's own city or region rather than a lookalike
# from somewhere else. Stock had real ice caves (Siberia) and real volcanoes
# (Etna, Nicaragua) — right subject, wrong continent. A page selling this trip
# cannot carry them.
OVERRIDES = {
    "WBCHET": {
        "d02": [("stock", ("d02_ordos_grassland", 5), "蒙古包群实拍"),
                ("stock", ("d02_ordos_grassland", 1), "草原孤包")],
        "d03": [("stock", ("d03_xiangshawan", 1), "沙丘驼队"),
                ("stock", ("d03_xiangshawan", 2), "沙脊光影")],
        # 万年冰洞:stock 只有西伯利亚冰川冰洞。改用当天另一处真实景点。
        "d04": [("stock", ("d04_hanging_village", 1),
                 "悬空村(芦芽山)——当日另一真实景点;万年冰洞无合规实拍")],
        # 应县木塔:前 4 个候选是大雁塔和西安城墙,第 5 个才是真的。
        "d05": [("stock", ("d05_yingxian", 5), "应县木塔,看图确认"),
                ("stock", ("d05_xinzhou", 4), "山西古城街景")],
        "d06": [("stock", ("d06_yungang", 1), "云冈石窟大佛"),
                ("stock", ("d05_datong_city", 6), "大同九龙壁")],
        # 乌兰哈达火山:stock 只有埃特纳和尼加拉瓜。改用当天落脚城市。
        "d07": [("stock", ("d07_region_hohhot", 1),
                 "呼和浩特大召寺——当日落脚城市;乌兰哈达火山无合规实拍")],
        # 康巴什:候选 #2#3 标题写 Mongolian Government Palace,实为蒙古国乌兰巴托,已排除。
        "d08": [("stock", ("d08_kangbashi", 1), "康巴什城市广场;#2#3 系蒙古国已排除")],
    },
    "WBCURC": {
        "d03": [("file",
                 "/private/tmp/claude-501/-Users-wangchengtai-Documents-webuytravel/"
                 "eed9efad-412f-4396-8741-c38ed4eaf3f1/scratchpad/wbcurc_day3/"
                 "candidate1_full.jpg",
                 "可可托海额尔齐斯大峡谷")],
        # 坎儿井:stock 全是泛化农业灌溉,无一是坎儿井。按区域规则改用新疆区域图。
        "d10": [("stock", ("d07_kokdala", 3),
                 "新疆区域实拍——坎儿井无合规实拍")],
    },
    "WBCKWE": {
        "d01": [("stock", ("d01_chongqing", 2), "重庆夜景")],
        "d06": [("stock", ("d06_kala_miao", 5), "苗族传统服饰")],
    },
}

PRODUCTS = {
    "WBCKWE": ("CHN", ["tours/115-9d8n-discover-the-natural-wonders-of-guizhou",
                       "tours/108-8d7n-chongqing-wulong-dazu-world-cultural-heritage"]),
    "WBCURC": ("CHN", ["tours/112-10d9n-travel-with-marcus-chin-altay-wonders"]),
    "WBCHET": ("CHN", []),
}

if __name__ == "__main__":
    for code, (region, tours) in PRODUCTS.items():
        plan = compose(code, region, tours, OVERRIDES.get(code, {}))
        fill_carousel(plan, code, tours)
        removed = dedupe(plan, cross_slot=bool(tours))
        materialise(plan, WORK / code / "out")
        plan.to_json(WORK / code / "plan.json")
        name = json.loads((WORK / code / "itinerary.json").read_text("utf-8"))
        render(plan, WORK / code / f"{code}_review.html",
               tour_name=name["product_name"]["en"])
        days = len({p.position for p in plan.of("section")})
        print(f"{code}: sections={len(plan.of('section'))} over {days} days | "
              f"carousel={len(plan.of('carousel'))} | thumb={len(plan.of('thumbnail'))} | "
              f"route={len(plan.of('route_map'))} | gaps={len(plan.gaps)} | deduped={len(removed)}")
        for g in plan.gaps:
            print(f"    GAP day {g.position}: {', '.join(g.subjects)[:70]}")
