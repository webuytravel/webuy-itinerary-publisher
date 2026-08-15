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
from lib.image_plan import (ImagePlan, Placement, assign_trip_photos, dedupe,
                            materialise, section_gap)
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
    # ①这一级是可选的。前五个产品都是从行程册进来的,所以 pdf_images.json 一定
    # 存在;2026-08-15 这一批相反——产品早就在 Skybear 上,行程文本是从生产读回来
    # 的,根本没有册子。缺册子不是错误状态,只是少一级图源,不该让整个 compose
    # 打不开。**注意这跟「跑了抽图但文件不在」不是一回事**:那种情况下 materialise
    # 仍然会因为 src_path 指不到文件而报错退出(见 3. 节那段 refusing to
    # materialise),所以放宽这里不会让缺图静默溜过去。
    pdf_path = base / "pdf_images.json"
    raw = json.loads(pdf_path.read_text("utf-8")) if pdf_path.exists() else []
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
    # ②Commons(DESIGN 3.35)。和 stock 同一个形状,所以下面的 override 分支
    # 只差 credit/license 要原样带过去——Commons 是唯一给出作者和许可证的源。
    commons = base / "commons.json"
    out["commons"] = json.loads(commons.read_text("utf-8")) if commons.exists() else {}
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


def trip_pool(code: str, picks: list[tuple]) -> list[Placement]:
    """Resolve `TRIP_PICKS` into a pool `assign_trip_photos` can draw from.

    These never enter the plan by themselves — a landmark card has to match
    them first. Raising on a missing block is the same rule as everywhere
    else here: a pick that points at nothing is a wiring error, and the cost
    of letting it pass silently is a card that quietly stays empty.
    """
    if not picks:
        return []
    data = load(code)
    out = []
    for kind, ref, note in picks:
        # ③ 和 ④ 两级都要能进景点卡。原来这里只收 commons,是因为 2026-08-14
        # 那一批的 trip 图全部来自 Commons;而 6.06 量出来的结论恰恰是那样做
        # 买到了准确性、赔掉了美学(五个产品饱和度 0.235–0.319 对房子 0.421)。
        # stock 是**唯一**按「好看」组织的一级,把它挡在景点卡外面等于把那根轴
        # 关掉。两级的取舍不同,所以都留着,由人逐张定。
        if kind == "commons":
            table, fallback_credit = data["commons"], "Wikimedia Commons"
            hint = f"先跑 `python3 bin/fetch_commons.py {code}`"
        elif kind == "stock":
            table, fallback_credit = data["stock"], "stock"
            hint = f"先跑 `python3 bin/fetch_stock.py {code}`"
        else:
            raise SystemExit(f"{code}: TRIP_PICKS 只支持 commons / stock,收到 {kind!r}")
        block, n = ref
        blk = table.get(block)
        row = next((c for c in (blk or {}).get("candidates", []) if c["n"] == n), None)
        if row is None:
            raise SystemExit(
                f"{code}: TRIP_PICKS 指向 {kind}:{block}#{n},没找到 —— {hint}")
        out.append(Placement(
            slot="trip", position=blk["day"], origin="web",
            subject=blk["subject"], source_ref=row["url"], src_path=row["path"],
            # stock 没有作者字段,退回来源名(pexels/unsplash);commons 两样都有,
            # 原样带走(DESIGN 3.35:不要在管线里把 credit/license 丢掉)。
            credit=row.get("credit") or row.get("source") or fallback_credit,
            license=row.get("license", ""), note=note))
    return out


def compose(code: str, region: str, tours: list[str], overrides: dict) -> ImagePlan:
    data = load(code)
    cat_rows = catalogue_for(code, tours)
    plan = ImagePlan(type_code=code, region=region)

    used_pdf, used_cat, chosen_cat = set(), set(), []

    for section in data["itinerary"]["sections"]:
        day = section["day"]
        subjects = [t["photo_subject"] for t in section.get("trip_items", [])
                    if t.get("photo_subject")]
        # 当天城市是最后一道搜索线索。景点条目可以一个 photo_subject 都没有
        # （抵达日写的是「Depart for Ordos via Kuala Lumpur」「Arrival and
        # Hotel Check-In」），但那天在表单上仍然是一个完整的 section，线上
        # 在售的参考产品 tours/112 第 1 天也是有图的。没有 subject 不等于
        # 那天不需要图，只等于「没人说过要搜什么」。
        fallback = [loc for loc in [(section.get("location") or {}).get("en")] if loc]
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
                # 和下面 commons 那一支一样要炸。原来这里是 `if row:` ——
                # 一个打错的 block 名或序号会**静默**跳过,那天就无声地少一张图,
                # 而摘要行只会报 gap,不会说「你指的那张不存在」。DESIGN 6.9 记的
                # 静默降级就是这一类,6.11 那批静默留空的天也是这么来的。
                if row is None:
                    raise SystemExit(
                        f"{code} {key}: stock {block}#{n} 不在 candidates.json 里 —— "
                        f"先跑 `python3 bin/fetch_stock.py {code}`")
                plan.placements.append(Placement(
                    slot="section", position=day, origin="web",
                    subject=data["stock"][block]["subject"],
                    source_ref=row["url"], src_path=row["path"],
                    credit=row["source"], note=note))
            elif kind == "cat":
                # ②这一级也需要显式指定的通道。token 匹配在图注写得准时够用，
                # 但同一天有多个景点、而图库只覆盖其中一两个时，先匹配上的那个
                # 会占掉名额，把覆盖得更好的那张挤掉——WBSZX1 第 3 天就是这样，
                # 自动匹配挑走了广东千古情(册子那张 991x369，裁到 section 要
                # 放大 2.44×)，把 1800px 的黄腾峡和黄飞鸿纪念馆晾在一边。
                row = next((r for r in cat_rows if r["image_id"] == ref), None)
                if row is None:
                    raise SystemExit(f"{code} {key}: catalogue image {ref} not in catalogue.json")
                used_cat.add(row["image_id"])
                chosen_cat.append(row)
                plan.placements.append(Placement(
                    slot="section", position=day, origin="catalogue",
                    subject=row["alt"], source_ref=row["tour"],
                    src_path="", credit="webuytravel.sg", note=note))
            elif kind == "commons":
                block, n = ref
                row = next((c for c in data["commons"].get(block, {}).get("candidates", [])
                            if c["n"] == n), None)
                if row is None:
                    raise SystemExit(
                        f"{code} {key}: commons {block}#{n} 不在 commons.json 里 —— "
                        f"先跑 `python3 bin/fetch_commons.py {code}`")
                # credit/license 原样带走。DESIGN 3.3 那张图的教训:出处丢了就
                # 只能靠 EXIF 反推,而 Commons 本来是把作者和许可证给全了的。
                plan.placements.append(Placement(
                    slot="section", position=day, origin="web",
                    subject=data["commons"][block]["subject"],
                    source_ref=row["url"], src_path=row["path"],
                    credit=row.get("credit") or "Wikimedia Commons",
                    license=row.get("license", ""), note=note))
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

        # 无条件记 gap。原来这里是 `if placed == 0 and subjects:`，那个
        # `and subjects` 把「一个 photo_subject 都没有的天」整个吞掉:既没有
        # 配图,也没有 gap,于是审核页上那天根本不出现,签字的人看不见它。
        if placed == 0:
            plan.gaps.append(section_gap(
                day, bool(section.get("trip_items")), subjects, fallback))

    pull_catalogue(code, chosen_cat)
    # Resolve by position, not by `alt`. The catalogue routinely carries two
    # images under one label ("Shawan Ancient Town" twice), so an alt lookup
    # can hand a placement the *other* file — same caption, different photo,
    # and nothing downstream would notice. `pending` walks the placements in
    # the order they were appended, which is the order `chosen_cat` was built.
    pending = [p for p in plan.placements
               if p.origin == "catalogue" and not p.src_path]
    for placement, row in zip(pending, chosen_cat):
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


def fill_carousel(plan: ImagePlan, code: str, tours: list[str], target: int = 8,
                  picks: list[tuple] | None = None, stock: dict | None = None):
    """Refill the carousel from what no day used.

    Sections win contested images: a day with no picture of the thing it
    sells is a worse page than a carousel one slide shorter, and the
    carousel can always be refilled from the leftovers — the reverse is not
    true.

    `picks` overrides the whole slot. It exists because the reprise path
    below is resolution-blind: it re-uses the day photos, and when those come
    from the brochure they are 685–760px — fine for a section tile, but the
    portrait carousel crop is 1080x1440, so a 685px source lands at 3.25×
    upscale and ships visibly soft. Brochure photos cannot be re-fetched
    larger; stock can (`bin/resharpen.py` swaps the preview for the original,
    2400–6000px). So where a product's headline scenery *does* have honest
    stock coverage, the carousel is stated explicitly and the brochure
    photos stay on their own day, where they are correctly sized.
    """
    if picks is not None:
        cat_rows = catalogue_for(code, tours)
        for i, (block, n, note) in enumerate(picks):
            head = "hero | " if i == 0 else ""
            if block.startswith("cat:"):
                # ②优先于③，所以轮播也要能点名图库图，而不是只能从 stock 里挑。
                image_id = block[4:]
                row = next((r for r in cat_rows if r["image_id"] == image_id), None)
                if row is None:
                    raise SystemExit(f"{code}: carousel pick {block} not in catalogue.json")
                pull_catalogue(code, [row])
                plan.placements.append(Placement(
                    slot="carousel", position=i, origin="catalogue",
                    subject=row["alt"], source_ref=row["tour"],
                    src_path=row["path"], credit="webuytravel.sg", note=head + note))
                continue
            row = next((c for c in (stock or {}).get(block, {}).get("candidates", [])
                        if c["n"] == n), None)
            if row is None:
                raise SystemExit(f"{code}: carousel pick {block}#{n} not in candidates.json")
            plan.placements.append(Placement(
                slot="carousel", position=i, origin="web",
                subject=(stock or {})[block]["subject"],
                source_ref=row["url"], src_path=row["path"],
                credit=row["source"], note=head + note))
        hero = next((p for p in plan.of("carousel") if p.position == 0), None)
        if hero:
            plan.placements.append(Placement(
                slot="thumbnail", position=0, origin=hero.origin,
                subject=hero.subject, source_ref=hero.source_ref,
                src_path=hero.src_path, credit=hero.credit, license=hero.license))
        return

    used = {p.src_path for p in plan.placements}
    pool = []
    for row in catalogue_for(code, tours):
        path = WORK / code / "cat" / f"{row['image_id']}.jpg"
        if str(path) not in used:
            pool.append(row)

    # One slide per landmark first. The catalogue carries two or three shots
    # of each place, and taking the pool in order gave WBCKWE a carousel of
    # Huangguoshu Waterfall ×3 + Jiaxiu Pavilion ×2 + Huaguoyuan ×2 — seven
    # slides, three subjects. `dedupe` never caught it: its same-subject rule
    # is keyed on (slot, position), and every carousel image sits at its own
    # position. Variety has to be chosen here, where the pool is picked.
    seen: set[str] = set()
    picks = []
    for row in pool:
        if row["alt"] in seen:
            continue
        seen.add(row["alt"])
        picks.append(row)
        if len(picks) == target:
            break
    # Only if the catalogue genuinely has fewer distinct landmarks than the
    # carousel has slots do we fall back to a second shot of one we already
    # used — a shorter carousel would be the worse trade.
    if len(picks) < target:
        chosen = {r["image_id"] for r in picks}
        picks += [r for r in pool if r["image_id"] not in chosen][:target - len(picks)]
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
    # WBLJG9 的 section 层。每天一张,而且刻意避开当天景点卡用掉的那几张——
    # assign_trip_photos 会硬性禁止当天的卡复用 section 的源文件(DESIGN 6.05),
    # 所以这里选的每一张都是那一块里没有进 TRIP_PICKS 的。
    # D1 不在下面:那天只有一张「夜间航班前往丽江」的交通卡,没有落地活动,
    # 属于 3.0 里「纯回程/纯飞行」那一类。**留空是要人点头的,不是我替它决定的**,
    # 所以它会作为 GAP 出现在摘要里。D9 抵达新加坡同理。
    "WBLJG9": {
        "d02": [("stock", ("d02_dali_ancient_city", 4), "大理城楼夜景,金光 s0.864")],
        "d03": [("stock", ("d03_bai_tie_dye_textile", 4), "扎染纹样特写,青碧 s0.528")],
        "d04": [("stock", ("d04_lige_peninsula_lugu_lake", 3), "枯树与木栈桥 s0.406")],
        "d05": [("stock", ("d05_lugu_lake_sunrise", 6), "湖面日出 s0.441")],
        "d06": [("stock", ("d06_blue_moon_valley_lijiang", 1), "秋林与松绿水 s0.387")],
        "d07": [("stock", ("d07_yuhu_village_lijiang", 2), "白墙纳西院落,蓝天 s0.293")],
        "d08": [("stock", ("d08_black_dragon_pool_lijiang", 6), "黑龙潭桥与雪山 s0.373")],
    },
    # WBXMNM 的 section 层,同样每天一张、且避开当天卡用掉的。
    "WBXMNM": {
        "d01": [("commons", ("d01_xunpu_village_quanzhou", 1), "宫庙前红妆院落 s0.467")],
        "d02": [("stock", ("d02_chaozhou_ancient_city", 2), "潮汕庙宇飞檐,蓝天 s0.410")],
        "d03": [("commons", ("d03_jieyang_confucian_temple", 5), "学宫大殿与庭院 s0.242")],
        "d04": [("commons", ("d04_fujian_tulou_earthen_building", 1), "油菜花前的土楼 s0.590")],
        "d05": [("stock", ("d05_gulangyu_island_xiamen", 4), "红瓦屋顶与海 s0.303")],
        "d06": [("stock", ("d06_nanputuo_temple_xiamen", 1), "南普陀塔院 s0.297")],
    },
    # WB9XMN 粤东。d05 不在下面——饶平/梅州那一天两个景点(龙湖古寨、道韵楼)
    # 四级图源全废,连一张能当天头的真图都没有,所以它会作为 GAP 出现在摘要里
    # 等人点头,而不是由我拿别处的土楼顶上去(3.4)。
    "WB9XMN": {
        "d01": [("stock", ("d01_huacheng_square_guangzhou", 2), "珠江夜景天际线 s0.646")],
        "d02": [("commons", ("d02_jieyang_confucian_temple", 4), "揭阳学宫庭院 s0.258")],
        # 南澳岛当天唯一带 GPS 且在闸门以上的真图。自然之门那张卡拿不到图,
        # 但这一张确实是南澳岛,当天头用它不算失真。
        "d03": [("commons", ("d03_nan_ao_island_coast", 5), "南澳九溪澳天后宫 gpsOK s0.251")],
        # 潮州这一天所有真图都在闸门以下(老城古民居 6 张 0.088–0.148、
        # 牌坊街 Commons 6 张 0.055–0.175)。唯一闸门以上又确属潮州的是这张
        # stock 牌坊,所以它进 section 而不是进牌坊街那张卡——见交付说明。
        "d04": [("stock", ("d04_chaozhou_paifang_street_archways", 1), "潮州牌坊 s0.256")],
        "d06": [("commons", ("d06_yannanfei_tea_plantation_meizhou", 5), "雁南飞茶垄 s0.310")],
        "d07": [("commons", ("d07_wanlu_lake_heyuan", 2), "万绿湖林间远眺 s0.315")],
    },
    # WBYNG 怒江。d08 不在下面:纯回程航班,和 WBLJG9 的 D9 同一类,留空要人点头。
    # d02–d04 三天都在怒江大峡谷里走,section 用的是同一个 block 里三张不同的
    # 河谷航拍(#5/#2/#3),卡上用的是另外两张(#6/#4),按 sha1 互不相同。
    "WBYNG": {
        "d01": [("stock", ("d01_fly_to_kunming_and_mangshi", 1), "昆明暮色城市与水面 s0.386")],
        "d02": [("stock", ("d02_nujiang_grand_canyon", 5), "怒江河谷群山 s0.340")],
        "d03": [("stock", ("d02_nujiang_grand_canyon", 2), "怒江河谷云雾航拍 s0.256")],
        "d04": [("stock", ("d02_nujiang_grand_canyon", 3), "怒江河谷俯瞰 s0.307")],
        # 天头图特意换成东竹林寺这一块。原来用的是 d05_feilai_temple_deqin#1
        # (云南梅里白塔),而 D6 的「飞来寺观景台」那张卡的 photo_subject 里
        # 同样有「飞来寺」,于是那张白塔被 D6 的卡又用了一次——同一张照片在
        # 页面上出现两处。东竹林寺这一块 D6 没有任何一张卡会去匹配。
        "d05": [("commons", ("d05_dongzhulin_monastery_shangri_la", 2), "东竹林寺 gpsOK s0.268")],
        "d06": [("stock", ("d06_meili_snow_mountain_kawagarbo_sunr", 4), "梅里日照金山 s0.273")],
        "d07": [("stock", ("d07_dukezong_ancient_town_shangri_la", 1), "香格里拉全景 s0.286")],
    },
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
        # 乌兰哈达火山:stock 只有埃特纳和尼加拉瓜,所以 08-13 那轮只能拿当天
        # 落脚城市顶上。08-14 Commons 给出三张带 GPS 且落在内蒙范围内的火山口
        # 航拍,这个替代不再必要——火山排前面,大召寺留作第二张。
        # 它写在产品 highlights 第 4 条,拿城市照顶替是失真的。
        "d07": [("commons", ("d07_ulan_hada_volcano_geopark", 1),
                 "乌兰哈达火山口航拍,带 GPS"),
                ("stock", ("d07_region_hohhot", 1), "呼和浩特大召寺——当日落脚城市")],
        # 康巴什:候选 #2#3 标题写 Mongolian Government Palace,实为蒙古国乌兰巴托,已排除。
        "d08": [("stock", ("d08_kangbashi", 1), "康巴什城市广场;#2#3 系蒙古国已排除")],
    },
    "WBCURC": {
        # Path is repo-relative like every other source. It used to point into
        # an agent session's scratchpad, which survives only until that
        # scratchpad is cleaned — after which this re-runs "successfully" and
        # silently drops day 3's photo, because a missing `src_path` only ever
        # becomes a note on the placement.
        "d03": [("file", "work/WBCURC/cand/d03_keketuohai_canyon.jpg",
                 "可可托海额尔齐斯大峡谷")],
        # 坎儿井:stock 全是泛化农业灌溉,无一是坎儿井。按区域规则改用新疆区域图。
        # (08-14 复查:Commons 搜 Karez Well 返回的是美军在阿富汗的照片,更糟,
        #  所以这条区域替代继续保留。)
        "d10": [("stock", ("d07_kokdala", 3),
                 "新疆区域实拍——坎儿井无合规实拍")],
        # D1 抵达乌鲁木齐。行程原文只有「飞 + 接机 + 入住」,没有游览活动,
        # 但用户 08-14 定的范围里包含它。入夜城市灯光配傍晚抵达是贴的。
        "d01": [("commons", ("d12_free_time_in_urumqi", 1),
                 "入夜城市灯光——抵达当晚")],
        # D12 乌鲁木齐自由活动。08-13 这天是静默留空的(DESIGN 6.11),而它有
        # 整个白天的自由活动,不是纯回程日——线上参考产品 tours/112 只有最后
        # 一天是空的。城市背后的天山雪线是乌鲁木齐最好认的特征。
        "d12": [("commons", ("d12_free_time_in_urumqi", 6),
                 "乌鲁木齐城区与天山雪线")],
    },
    "WBCKWE": {
        "d01": [("stock", ("d01_chongqing", 2), "重庆夜景")],
        "d06": [("stock", ("d06_kala_miao", 5), "苗族传统服饰")],
    },
    # WBINC9 是第一个在②图库这一级拿到 0 张的产品:webuytravel.sg 没有宁夏在售
    # 产品,唯一相邻的内蒙古沙漠产品 tours/75 全站只挂 1 张图。所以除册子自带的
    # 5 张外全部来自 stock,且逐张看过。
    # 第 2 天不在这里 —— 宁夏博物馆和览山公园两个主体,stock 12 张里没有一张是
    # 对的(返回嘉峪关、中国大运河博物馆、丽江黑龙潭),没有可用的替代,所以
    # 故意留成 gap 让审核页显式报出来,而不是拿一张认不出的中国城市图充数。
    # WBSZX1 的图源结构和 WBINC9 相反:②图库(tours/118 同区域同主题在售产品)
    # 覆盖了顺峰山、欢乐海岸、黄飞鸿纪念馆、黄腾峡、沙湾古镇,册子自带图覆盖了
    # 深圳湾、赤坎古镇、日月贝、千古情演出。缺口只剩首尾两个交通日和几个
    # 城市地标。
    "WBSZX1": {
        # 抵达日,册子只写接机入住。用深圳夜景天际线(平安金融中心可辨)。
        "d01": [("stock", ("d01_shenzhen_skyline", 2), "深圳湾夜景天际线,平安金融中心形态可辨")],
        # 自动匹配会挑走册子那张千古情演出图(991x369,裁到 section 要放大
        # 2.44×),把 1800px 的黄腾峡挤掉。这里点名换成两张图库原图。
        # 岭南新天地和广东千古情在 CMS 里只有 ~380x510,已从 catalogue.json 剔除。
        "d03": [("cat", "7vb1txIk", "黄飞鸿纪念馆(位于佛山祖庙内),CMS 图注,已授权"),
                ("cat", "TM550Omr", "黄腾峡天门玻璃桥,1800px 原图")],
        "d04": [("cat", "wfUiCnbg", "沙湾古镇,CMS 图注,已授权"),
                ("stock", ("d04_pearl_river", 3), "珠江夜游观光船实拍——当日必需自费项目")],
        "d06": [("stock", ("d06_zhuhai_fisher", 1), "珠海渔女像与情侣路海滨"),
                ("cat", "HTlwuVEv", "欢乐海岸")],
        # 深中通道 6 张候选都是珠三角跨海大桥,但没有一张能确认就是深中通道
        # (港珠澳大桥形态相近)。地域与类型都对,主体只写到「跨海大桥」。
        "d07": [("stock", ("d07_shenzhong_link", 1), "珠三角跨海大桥晨景;是否深中通道本体未确认")],
    },
    "WBINC9": {
        # D2 宁夏博物馆 / 览山公园。08-13 这是 plan.gaps 里唯一一条「有景点却
        # 一张图都没找到」的记录:stock 两轮 18 张全废(#2 是西安大雁塔,
        # 6.7 记过)。08-14 Commons 直接给出馆舍外观和中庭,主体确定无误。
        "d02": [("commons", ("d02_ningxia_museum_yinchuan", 5), "宁夏博物馆馆舍外观"),
                ("commons", ("d02_ningxia_museum_yinchuan", 6), "馆内中庭")],
        # D6 一百零八塔。stock 搜「一百零八塔」返回的是大理三塔(6.7),
        # 所以原来这天靠册子那张 590px 顶着。Commons #1 带 GPS,塔阵水中倒影。
        # 沙坡头本体无合规实拍(stock 返回张掖丹霞和交河故城)。这两张不冒充
        # 沙坡头,卖的是当天真实存在的两个体验:沙丘徒步/滑沙,和沙漠营地观星。
        "d05": [("stock", ("d05_sand_sliding", 1), "沙丘实拍(未标注具体地点);沙坡头景区本体无合规实拍"),
                ("stock", ("d05_stargazing", 5), "沙漠营地夜间帐篷观星——当日真实体验")],
        # 贺兰山岩画整块作废:#1 无可辨刻画,#6 是现代红漆题字的景观石。
        "d07": [("stock", ("d07_zhenbeipu", 5), "西北夯土城堡片场街景,类型与地域相符(具体是否镇北堡待复核)"),
                ("stock", ("d07_winery", 1), "岩山脚下葡萄园,与贺兰山东麓产区形态相符")],
        # 驼车整块作废:6 张全是单峰驼 + 南亚服饰(拉贾斯坦/信德),非中国双峰驼。
        "d08": [("stock", ("d08_shuidonggou", 4), "黄土峡谷内骑乘,地貌与活动均与水洞沟相符")],
    },
}

# 显式指定的轮播,用于册子图太小、又确实有诚实的高分辨率 stock 可用的产品。
# 每条同样是看过图才写进来的;`hero_*` 这批是专门为轮播补取的大图。
CAROUSEL = {
    # ②图库图和③stock 混排:图库这一级优先,但它只覆盖 4 个景点,而且轮播
    # (尤其 1080x1440 的竖版)需要 1080px 以上的源图,册子那批 700–1000px
    # 的图放进来会明显发虚,所以册子图只留在当日 section。
    "WBSZX1": [
        ("d04_canton_tower", 3, "广州珠江新城夜景天际线——行程里最大的城市"),
        ("cat:Jmz4i0ph", 0, "顺德欢乐海岸,1916px 原图"),
        ("food_dim_sum", 3, "广府点心宴——这是美食团,餐食是卖点不是附注"),
        ("cat:LEiTP6tQ", 0, "黄腾峡天门玻璃桥"),
        # 这两张刻意与当日配图错开:渔女像和深圳天际线各自已经用在第 6、第 1 天,
        # 跨槽去重会把轮播里的那张删掉(线上产品的轮播图和日程图本来就不重样)。
        ("food_dim_sum", 5, "蒸笼点心;八条美食 highlights 撑起两张轮播不算多"),
        ("cat:LltbVaVY", 0, "沙湾古镇"),
        ("d01_shenzhen_skyline", 5, "深圳夜景另一机位,与第 1 天当日配图不同张"),
        ("cat:8ben3nQr", 0, "顺峰山大牌坊"),
    ],
    "WBINC9": [
        ("hero_yellow_river", 4, "黄河嵌入式曲流航拍——产品名的主题,与册子封面同一意象"),
        ("hero_desert_dunes", 1, "沙丘航拍;行程实际穿越腾格里与阿拉善沙漠"),
        ("hero_stone_forest", 2, "赭色层理石柱,与册子黄河石林实拍形态一致(具体机位未核实)"),
        ("d05_stargazing", 5, "沙漠营地夜间观星——第 5 天真实体验"),
        ("hero_helan", 1, "干旱岩质山脉 + 荒草前景,与贺兰山形态相符"),
        ("d07_zhenbeipu", 5, "西北夯土城堡片场街景"),
        ("hero_desert_dunes", 4, "金色沙脊"),
        ("d08_shuidonggou", 4, "黄土峡谷"),
    ],
}

# 景点卡专用的选片。和 OVERRIDES 一样是编辑决策——每一条都是有人看过图才写下的,
# 区别只在于它落到 Trip Photos 而不是 Section Photos。
#
# 为什么要分开:线上三个已发布的内蒙产品 Section Photos 全是 0,图全挂在景点卡上
# (docs/DESIGN.md 1.1)。一天有五张好图时,要的是一张 section + 四张卡,
# 不是五张 section。这些条目不会自己进 plan,只有当某张景点卡的主体匹配上才会进。
#
# 2026-08-14 WBCHET 这一批:98 张 Commons 候选逐张看过,留 25 张(审核页已签字)。
# 被整块否决的 12 组里,`d06_shuttle_included_exterior_viewing` 六张全是美国航天
# 飞机「发现号」——行程原文写的是「含摆渡车」,shuttle 撞词。
TRIP_PICKS = {
    # 景点卡专用的选片。和 OVERRIDES 一样是编辑决策,区别只在于它落到
    # Trip Photos 而不是 Section Photos(分开的理由见 docs/DESIGN.md 1.1:
    # 线上三个已发布的内蒙产品 Section Photos 全是 0,图全挂在景点卡上)。
    #
    # 2026-08-14 第二轮重挑。第一轮只有准确性一根轴,结果五个产品的饱和度
    # 无一达到自家图库的水准(0.235–0.319 对 0.421),业务同事看生产页面
    # 提了「色彩不要灰暗」。现在按两轴挑,和印刷册子那边一致
    # (docs/DESIGN.md 6.06)。每条后面的 s0.xx 是实测饱和度,房子标准是 0.421、
    # 闸门(第 10 百分位)是 0.181。
    #
    # **美学分不是唯一标准。** 三处明显的反例,都按主体价值压过了分数:
    #   广州塔那组分最高的 #1(1.08)画面里根本不是广州塔;
    #   火焰山分最高的是山下骆驼(1.09),山体本身只有 0.92,但山体才是主角;
    #   黄果树分最高的 #3(1.08)是夜间彩灯秀,和册子调性不符。
    "WBCHET": [
        # D6 悬空寺:换掉原来的 #3/#5/#6(s0.11–0.16,灰崖壁和题刻)
        ("commons", ("d06_hanging_temple_hunyuan", 1), "崖壁全景,绿 s0.26"),
        ("commons", ("d06_hanging_temple_hunyuan", 2), "栈道游客,能看清悬空结构 s0.20"),
        ("commons", ("d06_hanging_temple_hunyuan", 4), "红墙门楼 s0.23"),
        # D5 大同古城:#2 疑似不是大同(像应县木塔)、#3 是节庆花灯,都没选
        ("commons", ("d05_datong_ancient_city", 5), "城墙与拱门,蓝天 s0.31"),
        ("commons", ("d05_datong_ancient_city", 1), "城楼正面,蓝天 s0.29"),
        ("commons", ("d05_datong_ancient_city", 6), "寺院院落红灯笼 s0.28"),
        # D5 应县木塔:#6 是展柜里的模型不是实景,#4 是屋顶垂直航拍
        ("commons", ("d05_yingxian_wooden_pagoda", 1), "木塔全景,蓝天 s0.33"),
        ("commons", ("d05_yingxian_wooden_pagoda", 5), "牌楼取景,塔在其后 s0.36"),
        ("commons", ("d05_yingxian_wooden_pagoda", 2), "斗拱细部,红木 s0.60"),
        # D7 乌兰哈达火山:#2 火山口深色岩 s0.14 不达标,换成地质公园游客区
        ("commons", ("d07_ulan_hada_volcano_geopark", 3), "地质公园游客区 s0.27"),
        # D3 响沙湾:去掉 #5(沙漠泳池,灰天 s0.12)
        ("commons", ("d03_xiangshawan_desert", 2), "骑骆驼队列,金沙 s0.37"),
        ("commons", ("d03_xiangshawan_desert", 1), "沙漠越野车 s0.34"),
        ("commons", ("d03_xiangshawan_desert", 4), "沙丘中白色穹顶度假区 s0.26"),
        # D6 云冈:#5 #4 是黑白老明信片。两个云冈块只各留一张,免得一天全是石窟
        ("commons", ("d06_yungang_grottoes_datong", 3), "露天大坐佛 s0.26"),
        ("commons", ("d06_yungang_grottoes_datong", 1), "彩绘佛龛 s0.29"),
        ("commons", ("d06_yungang_grottoes_buddha_statues", 2), "崖壁大坐佛 s0.28"),
    ],
    "WBCURC": [
        # D7 果子沟大桥:换掉 #1/#2(s0.14–0.15,阴天灰)
        ("commons", ("d07_guozigou_bridge", 5), "桥 + 绿山谷 + 蓝天 s0.38"),
        ("commons", ("d07_guozigou_bridge", 3), "山谷中的桥,远景 s0.36"),
        ("commons", ("d07_guozigou_bridge", 4), "桥塔入云 s0.28"),
        # D7 赛里木湖
        ("commons", ("d07_sayram_lake", 6), "蓝湖绿草雪山 s0.56"),
        ("commons", ("d07_sayram_lake", 3), "湖面草岸雪山 s0.33"),
        ("commons", ("d07_sayram_lake", 1), "湖畔航标 s0.33"),
        # D4 喀纳斯:去掉 #1(晨雾骑手 s0.24 但整体闷)
        ("commons", ("d04_kanas_lake", 4), "河石与松绿水色 s0.34"),
        ("commons", ("d04_kanas_lake", 6), "松绿色河湾 s0.28"),
        ("commons", ("d04_kanas_lake", 5), "湖面针叶林雪山 s0.22"),
        # D5 禾木村:#5 是城市公交车
        ("commons", ("d05_hemu_village", 6), "河谷木屋航拍,蓝天 s0.39"),
        ("commons", ("d05_hemu_village", 4), "雪季河谷全景 s0.35"),
        ("commons", ("d05_hemu_village", 3), "秋色河滩木屋 s0.24"),
        # D5 五彩滩:整块只有这一张
        ("commons", ("d05_colourful_beach_burqin", 1), "赭色风蚀滩与河 s0.28"),
        # D9 独库公路:#1 #2 是城镇街口和白杨路,#6 #5 主体是路牌
        ("commons", ("d09_duku_highway", 3), "盘山公路穿林谷,蓝天 s0.25"),
        ("commons", ("d09_duku_highway", 4), "陡峭山谷中的公路 s0.21"),
        # D9 天山:换掉 #2(金色日照雪峰,分 0.49 太暗)
        ("commons", ("d09_tianshan_mountains", 1), "冰川谷与雪峰 s0.33"),
        ("commons", ("d09_tianshan_mountains", 6), "雪山群 s0.25"),
        # D11 火焰山:#5 分最低(0.92)但它是山体本身,主体压过分数
        ("commons", ("d11_flaming_mountains_turpan", 5), "赭红色风蚀山脊——主角 s0.41"),
        ("commons", ("d11_flaming_mountains_turpan", 3), "卧驼 s0.38"),
        ("commons", ("d11_flaming_mountains_turpan", 2), "卧驼(红鞍) s0.40"),
        # D11 打馕
        ("commons", ("d11_xinjiang_naan_making", 2), "馕坑里贴馕的手 s0.27"),
        # D12 乌鲁木齐:#1 入夜城市灯光(D1 的 section 也用它,见 OVERRIDES)
        ("commons", ("d12_free_time_in_urumqi", 1), "入夜城市灯光 s0.40"),
        # D7 薰衣草:#5 带 GPS 可验证,#3 无坐标但形态明确且极饱和
        ("commons", ("d07_ili_lavender_museum", 5), "薰衣草田带白云,带 GPS s0.33"),
        ("commons", ("d07_ili_lavender_museum", 3), "紫色薰衣草田 s0.87"),
        # D8 草原(区域级,不是篝火活动本身):换掉 #4(牧人驱牛 s0.28,阴天)
        ("commons", ("d08_xinjiang_grassland_bonfire_party", 2), "草原曲流河(区域图) s0.54"),
        ("commons", ("d08_xinjiang_grassland_bonfire_party", 5), "绿丘草原(区域图) s0.54"),
    ],
    "WBINC9": [
        # D6 西夏陵:#5 分最高但陵台太远看不清,#1 最灰
        ("commons", ("d06_western_xia_imperial_tombs_yinchua", 4), "陵区全景,绿草 s0.24"),
        ("commons", ("d06_western_xia_imperial_tombs_yinchua", 3), "两座陵台与远山 s0.24"),
        ("commons", ("d06_western_xia_imperial_tombs_yinchua", 2), "陵台正面 s0.22"),
        # D6 一百零八塔:#6 升为主选(塔阵全景 + 蓝天),#1 倒影最标志但灰
        ("commons", ("d06_108_pagodas_qingtongxia_hillside_w", 6), "塔阵侧面全景,蓝天 s0.27"),
        ("commons", ("d06_108_pagodas_qingtongxia_hillside_w", 1), "塔阵与水中倒影 s0.16"),
        # D2 宁夏博物馆:馆舍外观(s0.17)留给 section,卡用中庭和石雕
        ("commons", ("d02_ningxia_museum_yinchuan", 6), "中庭 s0.25"),
        ("commons", ("d02_ningxia_museum_yinchuan", 4), "石雕(馆藏) s0.18"),
        # D4 黄河石林:#1 是全部候选里最亮的一张
        ("commons", ("d04_yellow_river_stone_forest_jingtai_", 1), "石林柱群,蓝天 s0.64"),
        ("commons", ("d04_yellow_river_stone_forest_jingtai_", 2), "峡谷与谷底村落 s0.18"),
        # D5 沙坡头:整块只有这一张,而且是「沙漠与黄河相接」那个标志性视角
        ("commons", ("d05_shapotou_scenic_area_zhongwei_dese", 1), "沙丘俯瞰黄河绿洲 s0.23"),
        # D6 青铜峡
        ("commons", ("d06_qingtongxia_yellow_river_grand_can", 1), "拦河大坝 s0.23"),
        ("commons", ("d06_qingtongxia_yellow_river_grand_can", 2), "坝体全景 s0.21"),
        # D3 阿拉善:#5 分更高但画面抽象,#2 主体最对(沙丘倒映湖面)
        ("commons", ("d03_alxa_desert_off_road_vehicle_sand_", 2), "沙丘与湖 s0.18"),
        # D7 贺兰山岩画:全是**展柜里的岩画石板**,不是山体原位。换掉最灰的 #1
        ("commons", ("d07_helan_mountain_rock_art_petroglyph", 3), "岩画石板(展柜) s0.27"),
        ("commons", ("d07_helan_mountain_rock_art_petroglyph", 4), "动物岩画(展柜) s0.24"),
    ],
    "WBCKWE": [
        # D7 梵净山:**整个 red_cloud_golden_summit 块弃用**——六张全是雾里的
        # 灰石桥和题刻,饱和 0.06–0.12,是全部候选里最差的一组。同一座山的
        # mount_fanjing #6 是云海之上的金顶,s0.43,画面强一个量级。
        ("commons", ("d07_mount_fanjing", 6), "云海之上的金顶 s0.43"),
        ("commons", ("d07_mount_fanjing", 1), "雾中山脊上的红衣人 s0.25"),
        # D6 西江千户苗寨
        ("commons", ("d06_xijiang_qianhu_miao_village", 2), "满山吊脚楼与梯田 s0.23"),
        ("commons", ("d06_xijiang_qianhu_miao_village", 6), "木楼与梯田 s0.26"),
        ("commons", ("d06_xijiang_qianhu_miao_village", 4), "溪上吊脚楼 s0.19"),
        # D2 甲秀楼:整组都在 0.19–0.22,挑主体最完整的三张
        ("commons", ("d02_jiaxiu_pavilion", 2), "临水楼阁与绿树 s0.22"),
        ("commons", ("d02_jiaxiu_pavilion", 1), "楼与拱桥、河 s0.22"),
        ("commons", ("d02_jiaxiu_pavilion", 4), "石桥与楼 s0.20"),
        # D3 黄果树:#3 分最高(1.08)但是夜间彩灯秀,粉紫色和册子调性不符
        ("commons", ("d03_huangguoshu_waterfall", 2), "林隙中的瀑布,绿 s0.27"),
        ("commons", ("d03_huangguoshu_waterfall", 5), "瀑布与碧潭 s0.27"),
        ("commons", ("d03_huangguoshu_waterfall", 4), "瀑布全景 s0.23"),
        # D3 陡坡塘:换掉 #5 #6(s0.10–0.12)
        ("commons", ("d03_doupotang_waterfall", 1), "宽帘瀑布 s0.21"),
        ("commons", ("d03_doupotang_waterfall", 3), "蓝天下的宽帘瀑布 s0.22"),
        ("commons", ("d03_doupotang_waterfall", 4), "瀑布与游客 s0.20"),
        # D4 万峰林:#2 雾中版 s0.13 不达标,只留 #1
        ("commons", ("d04_wanfenglin_ten_thousand_peak_fores", 1), "峰丛与金黄坝子 s0.19"),
    ],
    "WBSZX1": [
        # D6 珠海渔女:换掉 #5(雾中 s0.13)和 #1(隔山雾 s0.19)
        ("commons", ("d06_zhuhai_fisher_girl_statue_lovers_r", 2), "海中礁石上的渔女与城市,蓝天 s0.53"),
        ("commons", ("d06_zhuhai_fisher_girl_statue_lovers_r", 3), "观景平台与渔女 s0.41"),
        ("commons", ("d06_zhuhai_fisher_girl_statue_lovers_r", 4), "「珠海渔女」题名石 s0.38"),
        # D3 佛山祖庙:换掉 #6(带 GPS 但 s0.11,灰)
        ("commons", ("d03_foshan_ancestral_temple", 1), "庙宇屋脊与棕榈,蓝天 s0.43"),
        ("commons", ("d03_foshan_ancestral_temple", 5), "红墙与金字牌匾 s0.37"),
        ("commons", ("d03_foshan_ancestral_temple", 4), "石狮与庙门 s0.26"),
        # D4 广州塔:#1 分最高(1.08)但画面里不是广州塔,主体错,不选
        ("commons", ("d04_canton_tower_guangzhou", 3), "塔与城市、珠江,蓝天 s0.38"),
        ("commons", ("d04_canton_tower_guangzhou", 4), "夜间彩光塔与江 s0.34"),
        ("commons", ("d04_canton_tower_guangzhou", 5), "粉光夜景 s0.26"),
        # D4 珠江夜游(册子上的必需自费项目):#2 是全部候选里最亮的一张
        ("commons", ("d04_pearl_river_night_cruise_guangzhou", 2), "游船与斜拉桥夜景 s0.75"),
        ("commons", ("d04_pearl_river_night_cruise_guangzhou", 3), "蓝光游船,带 GPS s0.32"),
        # D4 花城广场:换掉 #4(题名石但 s0.06)和 #5
        ("commons", ("d04_huacheng_square_guangzhou_cbd_skyl", 3), "CBD 塔楼,蓝天 s0.39"),
        ("commons", ("d04_huacheng_square_guangzhou_cbd_skyl", 1), "东塔西塔,蓝天 s0.20"),
        ("commons", ("d04_huacheng_square_guangzhou_cbd_skyl", 2), "现代建筑与绿地 s0.31"),
        # D2 顺峰山牌坊
        ("commons", ("d02_shunfeng_mountain_archway_shunde_f", 1), "夜间灯光牌坊 s0.38"),
        ("commons", ("d02_shunfeng_mountain_archway_shunde_f", 2), "牌坊与园景 s0.26"),
        # D5 赤坎古镇
        ("commons", ("d05_chikan_ancient_town_arcade_archite", 2), "河涌与骑楼群 s0.21"),
        # D7 深中通道:**整块弃用**。六张全是灰海灰天的高速公路,最好的
        # #1 也只有 s0.15,低于闸门。一张灰色的高速照片不是卖点,宁可这张卡空着。
    ],
    # 2026-08-15 WBLJG9(id 419,云南)。245 张候选(③107 + ④138)逐块看过。
    # 这是第一个「行程文本来自生产、不是册子」的产品,也是第一个 ④ 和 ③ 一起
    # 参与景点卡的产品——6.06 之后 stock 才被放进这一层,理由见 trip_pool。
    #
    # 三处按主体价值压过美学分的:
    #   lijiang_old_town S3(s0.456,全块最高)是香格里拉松赞林寺,**弃**;
    #   baisha_town C4/C5/C6(三张)是丽江的蓝色动车组,查询词退化撞的,**弃**;
    #   jade_dragon C3(s0.414)画面是印象丽江的红色剧场,不是雪山,**弃**。
    # 一处相反、美学分和主体刚好一致:impression_lijiang C2(s0.612)是全块
    # 唯一真的演出场地,同时也是最饱和的一张。
    "WBLJG9": [
        # D2 双廊古镇
        ("commons", ("d02_shuanglang_town", 5), "洱海边古镇航拍,秋色+湖蓝 s0.393"),
        ("commons", ("d02_shuanglang_town", 1), "湖上玻璃观景台 s0.376"),
        # D2 大理古城(洋人街另算)
        ("stock", ("d02_dali_ancient_city", 3), "城门牌坊街景,蓝天 s0.407"),
        ("commons", ("d02_dali_ancient_city", 5), "南城楼与人流 s0.269"),
        # D2 洋人街:夜市霓虹正是这条街的样子,而且是全块最饱和的
        ("commons", ("d02_dali_old_town_street", 3), "夜市霓虹招牌 s0.522"),
        ("commons", ("d02_dali_old_town_street", 4), "夜街店铺 s0.429"),
        # D2 理想邦 → 洱海。整块 12 张里 8 张低于闸门,是这个产品最灰的一块。
        ("stock", ("d02_erhai_lake_dali", 6), "洱海石桥与绿岸,全块唯一达标的构图 s0.444"),
        # D3 洱海日出(龙龛码头)
        ("commons", ("d03_erhai_lake_sunrise", 2), "深蓝洱海与积云 s0.484"),
        # D3 喜洲古镇:金色稻田配白族民居,喜洲的标志画面
        ("commons", ("d03_xizhou_town_dali", 1), "稻田与白族民居 s0.547"),
        ("stock", ("d03_xizhou_town_dali", 2), "白墙民居院落,蓝天 s0.293"),
        # D3 金花打跳 / 白族服饰
        ("stock", ("d03_bai_people_traditional_costume", 5), "街头打跳,盛装群舞 s0.327"),
        ("commons", ("d03_bai_people_traditional_costume", 1), "白族妇女表演 s0.367"),
        # D3 扎染:这一块是全产品最好的,过程 + 成品都有
        ("stock", ("d03_bai_tie_dye_textile", 6), "手浸靛蓝染缸,过程 s0.498"),
        ("stock", ("d03_bai_tie_dye_textile", 3), "橙墙前展开扎染布 s0.431"),
        # D4 泸沽湖
        ("commons", ("d04_lugu_lake", 3), "绿丘环抱的湖湾 s0.461"),
        # D4 里格半岛 / 情人滩
        ("stock", ("d04_lige_peninsula_lugu_lake", 1), "蓝湖与半岛全景 s0.542"),
        ("commons", ("d04_lige_peninsula_lugu_lake", 3), "里格半岛俯瞰,岛形清楚 s0.296"),
        # D4 摩梭篝火:没有一张真的篝火晚会。C2/C4 分更高(0.605/0.741)但族属
        # 存疑(看着更像彝族/藏族),按「宁可不用也不错标民族」取 C6。
        ("commons", ("d04_mosuo_people", 6), "木楞房前两位盛装妇女,族属可辨 s0.561"),
        # D5 泸沽湖日出。这里要**三张**,不是因为要挂三张,是因为 D4 也是泸沽湖:
        # token 匹配分不出「Lugu Lake」和「Lugu Lake sunrise」(两者都是 1.00),
        # 而 D4 先被处理、max_reuse=1,所以 D4 的卡会先把日出这张吃掉,D5 那张
        # 名字就叫「Lugu Lake Sunrise」的卡反而空着。多备两张,让 D4 吃饱之后
        # D5 还有得挑。
        ("stock", ("d05_lugu_lake_sunrise", 5), "金色日出与船影 s0.449"),
        ("stock", ("d05_lugu_lake_sunrise", 2), "晨雾中的日出湖面 s0.283"),
        ("stock", ("d05_lugu_lake_sunrise", 1), "朝霞映雪峰与村舍 s0.261"),
        # D5 猪槽船与里务比岛:橙色猪槽船就是这张卡的正主
        ("stock", ("d05_liwubi_island_lugu_lake", 4), "摩梭人划猪槽船 s0.472"),
        ("commons", ("d05_liwubi_island_lugu_lake", 1), "湖中岛屿与蓝湖 s0.446"),
        # D6 玉龙雪山
        ("stock", ("d06_jade_dragon_snow_mountain", 5), "石桥前雪峰,蓝天明信片 s0.458"),
        ("stock", ("d06_jade_dragon_snow_mountain", 4), "雪峰特写 s0.412"),
        ("stock", ("d06_jade_dragon_snow_mountain", 2), "木栈道通向雪山 s0.375"),
        # D6 蓝月谷 / 白水河
        ("stock", ("d06_blue_moon_valley_lijiang", 6), "松绿水与秋林 s0.520"),
        ("stock", ("d06_blue_moon_valley_lijiang", 2), "白水河阶梯状水台 s0.275"),
        # D6 印象丽江:全块唯一真的演出场地
        ("commons", ("d06_impression_lijiang_show", 2), "红色梯形剧场与雪山 s0.612"),
        # D7 玉湖村:C1 是唯一真的玉湖村(石头房),stock 六张全是别处
        ("commons", ("d07_yuhu_village_lijiang", 1), "石砌院落与草地 s0.310"),
        # D7 白沙古镇
        ("commons", ("d07_baisha_town_lijiang", 3), "集市与纳西妇女盛装 s0.353"),
        ("commons", ("d07_baisha_town_lijiang", 1), "夯土墙巷道 s0.307"),
        # D8 黑龙潭
        ("stock", ("d08_black_dragon_pool_lijiang", 4), "得月楼与玉龙雪山,标志构图 s0.379"),
        ("commons", ("d08_black_dragon_pool_lijiang", 6), "五孔桥与雪山 s0.394"),
        # D8 丽江古城与四方街
        ("commons", ("d08_lijiang_old_town", 4), "木构商铺石板街 s0.449"),
        ("commons", ("d08_lijiang_old_town", 1), "古城夜景 s0.448"),
        ("commons", ("d08_lijiang_old_town", 5), "大水车,古城入口标志 s0.261"),
    ],
    # 2026-08-15 WBXMNM(id 413,闽南 + 潮汕)。233 张候选(③89 + ④144)逐块看过。
    #
    # **这个产品和云南不是一个量级,原因是潮汕属于长尾。** D3(揭阳/汕头)那五块
    # 里,stock 返回的是西安城墙(进贤门那块 6 张里 4 张)、皖南宏村(小公园和棉湖
    # 两块)、北京颐和园和台北中正纪念堂(揭阳学宫那块);Commons 有真货但基本在
    # 闸门以下。潮州牌坊街 6 张 Commons **全部**低于 0.181。
    #
    # 因此有 6 张卡是**故意空着**的,不是漏了:
    #   D1 洛伽寺 / 侨批馆 —— 只有「某座闽南庙」「某栋殖民风建筑」,认不出是它;
    #   D3 棉湖古镇 —— 能用的全是皖南;
    #   D3 小公园 —— 唯一真的那张(C1)只有 s0.100,而闸门以上的全是宏村;
    #   D5 乳胶商场 —— 购物点,不是景点;退化搜 'Free Trade Zone' 还搜回了一张
    #                  尼日利亚 Lekki 自贸区的地图(GPS 已标出不在行程范围);
    #   D5 毓园 —— 林巧稚纪念园,Commons 0 张,stock 全是鼓浪屿泛拍。
    # 按 3.4:卖这条线路配别处的照片,问题不是侵权是广告不实。宁可空。
    "WBXMNM": [
        # D1 蟳埔村簪花 —— 这一块是全产品最好的,蚵壳厝和簪花都是独有的
        ("commons", ("d01_xunpu_village_quanzhou", 4), "盛装簪花妇女在宫庙前 s0.368"),
        ("commons", ("d01_xunpu_village_quanzhou", 3), "蚵壳厝墙面,蟳埔独有 s0.338"),
        # D1 西街与开元寺
        ("stock", ("d01_quanzhou_west_street_kaiyuan_templ", 3), "开元寺东西塔近景,蓝天 s0.375"),
        ("commons", ("d01_quanzhou_west_street_kaiyuan_templ", 5), "双塔越过红瓦屋顶 s0.324"),
        # D2 潮州古城:没有一张标准「古城全景」,用潮汕嵌瓷屋脊代表
        ("stock", ("d02_chaozhou_ancient_city", 6), "金red描金屋脊,潮汕庙宇 s0.418"),
        ("stock", ("d02_chaozhou_ancient_city", 4), "嵌瓷屋脊人物,潮汕工艺 s0.309"),
        # D2 牌坊街:Commons 六张全部低于闸门,只能用 stock 这一张
        ("stock", ("d02_chaozhou_paifang_street_archways", 1), "牌坊与红灯笼,蓝天 s0.256"),
        # D2 广济楼
        ("commons", ("d02_guangji_gate_chaozhou", 6), "城楼与城墙,暮色 s0.207"),
        ("commons", ("d02_guangji_gate_chaozhou", 4), "城楼正面,蓝天 s0.197"),
        # D2 入梦潮州:两张潮剧扮相,是全产品最饱和的一组
        ("stock", ("d02_chaozhou_night_performance", 2), "潮剧武生扮相 s0.662"),
        ("stock", ("d02_chaozhou_night_performance", 6), "潮剧青衣扮相 s0.438"),
        # D2 湘子桥
        ("commons", ("d02_guangji_bridge_chaozhou", 2), "桥上亭阁与彩旗 s0.484"),
        ("commons", ("d02_guangji_bridge_chaozhou", 3), "十八梭船连成的浮桥段 s0.363"),
        # D3 揭阳学宫
        ("commons", ("d03_jieyang_confucian_temple", 3), "大成门朱漆门扇 s0.476"),
        ("commons", ("d03_jieyang_confucian_temple", 2), "太和元气红照壁 s0.272"),
        # D3 中山骑楼街。**标注:骑楼是粤东到广府共有的形制,这张核不到具体城市。**
        # 按 6.8 的规矩,这类替代必须写出来,而且不重复使用。
        ("stock", ("d03_shantou_qilou_arcade_street", 5), "骑楼商行街景,城市未核实 s0.309"),
        # D3 进贤门:Commons C1 是唯一真的进贤门(stock 六张里四张是西安城墙)
        ("commons", ("d03_jinxian_gate_jieyang", 1), "进贤门城楼与绿化 s0.218"),
        # D4 土楼。**标注:行程写的是饶平道韵楼(八角形),这两张是通用福建土楼。**
        ("stock", ("d04_fujian_tulou_earthen_building", 4), "土楼檐口与红灯笼,蓝天 s0.412"),
        ("stock", ("d04_fujian_tulou_earthen_building", 5), "圆楼外观与入口 s0.196"),
        # D4 漳州古城
        ("stock", ("d04_zhangzhou_ancient_city", 5), "古城屋顶与塔 s0.337"),
        ("stock", ("d04_zhangzhou_ancient_city", 2), "院落盆景与老树 s0.395"),
        # D4 漳州文庙
        ("commons", ("d04_zhangzhou_confucian_temple", 5), "大成殿梁架斗拱 s0.445"),
        ("commons", ("d04_zhangzhou_confucian_temple", 1), "大成殿与月台 s0.200"),
        # D5 鼓浪屿
        ("commons", ("d05_gulangyu_island_xiamen", 1), "环岛夜景 s0.461"),
        ("stock", ("d05_gulangyu_island_xiamen", 3), "轮渡码头与岛景 s0.319"),
        # D5 万国建筑
        ("commons", ("d05_gulangyu_colonial_architecture", 2), "山坡老别墅群 s0.319"),
        ("commons", ("d05_gulangyu_colonial_architecture", 1), "红瓦屋顶密集俯瞰 s0.316"),
        # D5 龙头路:Commons 是唯一拍到真商业街的,stock 全是航拍泛景
        ("commons", ("d05_gulangyu_longtou_road_beach", 4), "龙头路人流商铺 s0.252"),
        # D6 南普陀寺
        ("commons", ("d06_nanputuo_temple_xiamen", 4), "大悲殿匾额与彩绘 s0.509"),
        ("commons", ("d06_nanputuo_temple_xiamen", 1), "天王殿正面与香客 s0.310"),
        # D6 沙坡尾
        ("stock", ("d06_shapowei_xiamen_harbour", 5), "日落渔船与海面 s0.364"),
        ("commons", ("d06_shapowei_xiamen_harbour", 1), "避风坞彩色渔船 s0.311"),
    ],
    # WB9XMN 粤东(潮汕/梅州/河源)。35 张卡里只有 15 张拿得到图,而这不是
    # 挑得不够狠——粤东和 WBXMNM 的 D3 是同一条长尾:Commons 有 8 个主体整块
    # 返回 0(祠堂、古寨、围龙屋、道韵楼、客家博物馆、甲第巷、陈慈黉故居、
    # 骑楼街),stock 在这一带的失败模式是 6.7 记的那一类,而且这一轮又添了
    # 三条新的,都是分数漂亮、地方不对:
    #   广济桥 stock#3 图注写「iconic Guangji Bridge」,画面是绿水里的养殖架;
    #   广济楼 stock#3 s0.451 是**福州**府城隍庙(匾额看得清清楚楚);
    #   潮州古城 stock#6 s0.418 图注自己写着 in Beijing。
    # 另有一整类「真的但灰」:小公园唯一真图 s0.100(和 413 同一张)、
    # 潮州老城古民居 6 张 0.088–0.148、牌坊街 Commons 6 张 0.055–0.175。
    # 按 3.4 全部留空,逐条见交付说明。
    "WB9XMN": [
        # D1 花城广场:两张都带 GPS。stock 那组分最高的 #2 s0.646 是珠江夜景
        # 天际线,不是广场本身,所以它去了 section。
        ("commons", ("d01_huacheng_square_guangzhou", 3), "广场与歌剧院 gpsOK s0.389"),
        ("commons", ("d01_huacheng_square_guangzhou", 2), "广场绿地与塔群 gpsOK s0.313"),
        # D1 广州塔:Commons #1 标题写着 Bank of Guangzhou Tower,画面里是两栋
        # 玻璃写字楼,根本没有广州塔——分 s0.401 排在前面,已排除。
        ("stock", ("d01_canton_tower", 2), "圆形取景框中的广州塔 s0.543"),
        ("commons", ("d01_canton_tower", 4), "广州塔与城市天际线 gpsOK s0.383"),
        # D1 永庆坊
        ("commons", ("d01_yongqingfang_guangzhou", 3), "永庆大街 gpsOK s0.284"),
        ("commons", ("d01_yongqingfang_guangzhou", 4), "永庆坊街景 s0.234"),
        # D1 李小龙祖居:行程把它写成佛山,但祖居实际在广州荔湾永庆坊,
        # Commons 六张的标题和 GPS 都指向那里,和行程顺序(紧接永庆坊)也对得上。
        # stock 那六张是佛山祖庙、佛山中山公园,主体就不对。
        ("commons", ("d01_bruce_lee_ancestral_home_foshan", 3), "祖居展陈空间 s0.321"),
        ("commons", ("d01_bruce_lee_ancestral_home_foshan", 4), "祖居厅堂 s0.255"),
        # D2 打铁街:Commons 六张分别在芬兰、阿拉斯加、爱尔兰、威斯康星,
        # 没有一张在中国。留下的这两张是打铁本身的特写,画面里没有可辨识的
        # 地点,属于「示意工艺」而不是「宣称地点」。
        ("stock", ("d02_blacksmith_forge_workshop", 5), "锻打火星,无可辨识地点 s0.586"),
        ("stock", ("d02_blacksmith_forge_workshop", 6), "烧红的铁与锤 s0.346"),
        # D2 无米粿:Commons 六张是澄海的虾干标本(带 GPS 但主体是干货不是粿)。
        ("stock", ("d02_chaoshan_street_food_dumpling", 1), "蒸笼粿品 s0.662"),
        # D2 揭阳古城(学宫):六张全部带 GPS,是这个产品里最干净的一块。
        ("commons", ("d02_jieyang_confucian_temple", 3), "学宫朱扉与斗拱 gpsOK s0.476"),
        ("commons", ("d02_jieyang_confucian_temple", 2), "学宫红墙 gpsOK s0.272"),
        # D2 龙眼南路美食街:这两张图注写的是揭阳,不是汕头。当天行程正好
        # 惠州→揭阳→汕头,同属潮汕,所以留着——但它不是那条街,交付说明里点名。
        # 同块 stock#4 s0.521 那张调色很好看的巷子,图注自己写着北京,已排除。
        ("stock", ("d02_chaoshan_night_food_street", 5), "揭阳街头小吃摊 s0.536"),
        ("stock", ("d02_chaoshan_night_food_street", 6), "揭阳夜市炉火 s0.369"),
        # D3 南澳大桥:桥塔上「南澳大桥」四个字在图里认得出来。stock 六张分别
        # 是海口世纪大桥、重庆、大连,全是别处的桥。
        ("commons", ("d03_nan_ao_bridge_shantou", 3), "南澳大桥夜景,桥名可辨 s0.509"),
        # D3 长山尾灯塔:标题带「南澳島長山尾燈塔」,背景就是南澳大桥。
        ("commons", ("d03_changshanwei_lighthouse_nan_ao", 2), "灯塔与南澳大桥,蓝天 s0.435"),
        # D3 鱼排出海:Commons 是美国国家档案馆和加拿大的蚝场。留下的两张
        # 画面里只有海和渔排,不指向任何地点,配「出海体验」这张活动卡成立。
        ("stock", ("d03_oyster_raft_aquaculture_sea", 6), "渔排航拍与作业船 s0.346"),
        ("stock", ("d03_oyster_raft_aquaculture_sea", 4), "海上渔排群 s0.271"),
        # D4 广济桥:浮桥段的红船,是这座桥最认得出来的一段。
        ("commons", ("d04_guangji_bridge_chaozhou", 3), "广济桥浮桥红船 s0.363"),
        # D4 广济楼:带 GPS 的三张都在闸门以下,这张 0.207 是唯一够线的真图。
        ("commons", ("d04_guangji_gate_chaozhou", 6), "广济门城楼 s0.207"),
        # D6 雁南飞:六张文件名就是 Yannanfei Tea Garden,全部够线。stock 那几张
        # 更艳的是杭州龙井和南京,已排除。整块偏雾,分数比肉眼观感乐观。
        ("commons", ("d06_yannanfei_tea_plantation_meizhou", 3), "茶田花径与场部 s0.369"),
        ("commons", ("d06_yannanfei_tea_plantation_meizhou", 2), "茶垄与林 s0.327"),
        # D7 万绿湖:#5 文件名写新丰江水库,那正是万绿湖的本名。
        ("commons", ("d07_wanlu_lake_heyuan", 4), "万绿湖正午,湖心岛与沙洲 s0.433"),
        ("commons", ("d07_wanlu_lake_heyuan", 1), "东源码头 s0.328"),
    ],
    # WBYNG 怒江+梅里+香格里拉。25 张卡里 13 张有图。这个产品的失败模式和
    # 粤东不一样:不是「没有」,是**同名异地**,而且四条都是分数最高的那张:
    #   普化寺 Commons 六张全在**山西五台山**(#2 s0.556);
    #   老虎跳 Commons 六张在**法国 Verdon 峡谷**和**俄勒冈 Columbia 峡谷**;
    #   龟山转经筒 Commons 六张全在**台湾桃园龟山**(其中一张是 M41 坦克);
    #   江边文化走廊 Commons 是**缅甸萨尔温江**(怒江出境后的名字),
    #     还混进了一张流量柱状图和一张流域地图。
    # 傈僳族那一块唯一的 Commons 是**泰国 Tha Ton** 的傈僳族少女,人对国别不对。
    "WBYNG": [
        # D2 勐焕大金塔:金孔雀 + 傣式金塔,德宏的形制,和芒市这座对得上。
        # 同块 stock#4 s0.860 是香格里拉的转经筒,已让它回到 D7 该去的卡上。
        ("commons", ("d02_menghuan_golden_pagoda_mangshi", 1), "大金塔与金孔雀 s0.295"),
        # D2 怒江大峡谷:这一块 stock 六张里五张图注直接写 Nujiang Valley,
        # 是整个产品最可靠的一组。#1 是虎跳峡(金沙江,不是怒江),已排除。
        ("stock", ("d02_nujiang_grand_canyon", 6), "峡谷村落与云上雪山 s0.581"),
        ("stock", ("d02_nujiang_grand_canyon", 4), "怒江河谷航拍 s0.406"),
        # D3 登埂澡堂会:江边的石砌浴池和木桩,就是澡堂会那片河滩。
        ("commons", ("d03_nujiang_hot_spring_riverside", 1), "登埂澡堂江边浴池 s0.272"),
        # D3 知子罗:带 GPS 的航拍,2024 年拍的。
        ("commons", ("d03_zhiziluo_abandoned_town_nujiang", 1), "知子罗航拍 gpsOK s0.264"),
        # D3 老姆登教堂:六张全部带 GPS。stock#1 是德钦茨中教堂,另一座,已排除。
        ("commons", ("d03_laomudeng_church_nujiang", 4), "教堂内部 gpsOK s0.270"),
        ("commons", ("d03_laomudeng_church_nujiang", 2), "教堂侧面 gpsOK s0.234"),
        # D4 怒江第一湾:马蹄形河湾,一眼认得出。同块 #2 s0.596 是一张
        # **肯塔基与田纳西州地图**的书页扫描,分数比真图高。
        ("commons", ("d04_first_bend_nu_river_bingzhongluo", 1), "怒江第一湾 s0.247"),
        # D5 飞来寺:#5#6 都是寺内实拍且够亮,#3 带 GPS。
        ("commons", ("d05_feilai_temple_deqin", 5), "飞来寺内部 s0.672"),
        ("commons", ("d05_feilai_temple_deqin", 6), "飞来寺迎宾 s0.568"),
        # D5 东竹林寺:四张带 GPS,法鼓那张 0.646 是整个产品最亮的 Commons。
        ("commons", ("d05_dongzhulin_monastery_shangri_la", 6), "东竹林寺法鼓 gpsOK s0.646"),
        ("commons", ("d05_dongzhulin_monastery_shangri_la", 3), "东竹林寺全景 gpsOK s0.412"),
        # D6 飞来寺观景台:观景台看出去就是这条梅里全景。
        ("commons", ("d06_feilai_temple_viewing_platform_mei", 2), "梅里雪山全景 s0.523"),
        # D6 日照金山:Commons 是白天的卡瓦格博峰,stock#1 才是金顶那一刻。
        # 两张都实拍梅里,一张给形一张给「日照金山」这四个字。
        ("commons", ("d06_meili_snow_mountain_kawagarbo_sunr", 1), "卡瓦格博峰 s0.556"),
        ("stock", ("d06_meili_snow_mountain_kawagarbo_sunr", 1), "梅里日照金山 s0.276"),
        # D7 松赞林寺:六张 panoramio 全是真的,挑最亮的两张。
        ("commons", ("d07_songzanlin_monastery_shangri_la", 3), "松赞林寺全景 s0.515"),
        ("commons", ("d07_songzanlin_monastery_shangri_la", 4), "松赞林寺经堂 s0.514"),
        # D7 独克宗古城:六张都带 GPS,但五张在闸门以下,只有这张够线。
        ("commons", ("d07_dukezong_ancient_town_shangri_la", 4), "古城天际线 gpsOK s0.222"),
        # D7 龟山转经筒:Commons 整块是台湾桃园,stock 这两张图注写明香格里拉。
        ("stock", ("d07_guishan_park_giant_prayer_wheel_sh", 1), "巨型转经筒暮色 s0.860"),
        ("stock", ("d07_guishan_park_giant_prayer_wheel_sh", 2), "藏式殿宇与经幡 s0.263"),
    ],
}

PRODUCTS = {
    "WBCKWE": ("CHN", ["tours/115-9d8n-discover-the-natural-wonders-of-guizhou",
                       "tours/108-8d7n-chongqing-wulong-dazu-world-cultural-heritage"]),
    "WBCURC": ("CHN", ["tours/112-10d9n-travel-with-marcus-chin-altay-wonders"]),
    "WBCHET": ("CHN", []),
    # 宁夏在 webuytravel.sg 上没有同区域在售产品可采(2026-08-13 实查 china-tours
    # 索引 12 个产品,最近的 tours/75 内蒙古沙漠全站只有 1 张图)。
    "WBINC9": ("CHN", []),
    # 相反的例子:tours/118 是同区域同主题的在售粤味美食团,14 张带 CMS 图注的
    # 授权图正好覆盖顺峰山、欢乐海岸、黄飞鸿纪念馆、岭南新天地、广东千古情、
    # 黄腾峡、沙湾古镇 —— ②这一级在有兄弟产品时的实际覆盖度。
    "WBSZX1": ("CHN", ["tours/118-7d6n-canton-gourmet-tour-2-0"]),
    # 2026-08-15 起这一批:产品已在 Skybear 上、行程文本从生产读回,没有册子,
    # webuytravel.sg 上也没有同区域在售的云南产品可采,所以 ①② 两级都是空的,
    # 全部靠 ③Commons + ④stock。
    "WBLJG9": ("CHN", []),
    "WBXMNM": ("CHN", []),
    # 2026-08-15 第二批。粤东和滇西北在 webuytravel.sg 上同样没有同区域在售
    # 产品可采,①② 依旧是空的。
    "WB9XMN": ("CHN", []),
    "WBYNG": ("CHN", []),
}

if __name__ == "__main__":
    # 只跑指定的产品。默认全跑会把已经审过的三个产品的 plan.json 连同
    # 它们的图一起重新生成,那是不必要的网络往返,也会让已签字的配图漂移。
    only = set(sys.argv[1:])
    for code, (region, tours) in PRODUCTS.items():
        if only and code not in only:
            continue
        plan = compose(code, region, tours, OVERRIDES.get(code, {}))
        stock = json.loads((WORK / code / "candidates.json").read_text("utf-8")) \
            if (WORK / code / "candidates.json").exists() else {}
        fill_carousel(plan, code, tours, picks=CAROUSEL.get(code), stock=stock)
        removed = dedupe(plan, cross_slot=bool(tours))
        # 景点卡这一层。放在 dedupe 之后:它复用的是去重之后真正留下的那些图,
        # 而不是可能马上被删掉的。也放在 materialise 之前,这样 trip 槽和别的槽
        # 一起编码,不会出现一半产物的 out/ 目录。
        itin = json.loads((WORK / code / "itinerary.json").read_text("utf-8"))
        assign_trip_photos(plan, itin["sections"], score, MATCH_FLOOR,
                           extra=trip_pool(code, TRIP_PICKS.get(code, [])))
        materialise(plan, WORK / code / "out")
        plan.to_json(WORK / code / "plan.json")
        name = json.loads((WORK / code / "itinerary.json").read_text("utf-8"))
        render(plan, WORK / code / f"{code}_review.html",
               tour_name=name["product_name"]["en"])
        covered = {p.position for p in plan.of("section")}
        total_days = len(name["sections"])
        bare = [d for d in range(1, total_days + 1) if d not in covered]
        print(f"{code}: sections={len(plan.of('section'))} over {len(covered)}/{total_days} days | "
              f"carousel={len(plan.of('carousel'))} | thumb={len(plan.of('thumbnail'))} | "
              f"route={len(plan.of('route_map'))} | gaps={len(plan.gaps)} | deduped={len(removed)}")
        # 「over 7 days」这种说法读起来像在报进度,不像在报缺口——WBCHET 打的
        # 就是 `sections=9 over 7 days`,9 天的产品少了 2 天,没有人从这行字里
        # 看出来。把没有图的那几天点名列出来。
        if bare:
            print(f"    NO SECTION PHOTO: day(s) {', '.join(map(str, bare))} "
                  f"— 逐条见下方 GAP,每一条都要人决定")
        for g in plan.gaps:
            print(f"    GAP day {g.position}: {', '.join(g.subjects)[:70]}")
