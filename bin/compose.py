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
        # Path is repo-relative like every other source. It used to point into
        # an agent session's scratchpad, which survives only until that
        # scratchpad is cleaned — after which this re-runs "successfully" and
        # silently drops day 3's photo, because a missing `src_path` only ever
        # becomes a note on the placement.
        "d03": [("file", "work/WBCURC/cand/d03_keketuohai_canyon.jpg",
                 "可可托海额尔齐斯大峡谷")],
        # 坎儿井:stock 全是泛化农业灌溉,无一是坎儿井。按区域规则改用新疆区域图。
        "d10": [("stock", ("d07_kokdala", 3),
                 "新疆区域实拍——坎儿井无合规实拍")],
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
