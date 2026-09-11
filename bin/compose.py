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
two languages. The per-day overrides exist for the cases where that is not
enough and a human (or a multimodal pass) has already made the call.

**这个文件里没有任何 per-product 的编辑决策。** 哪天用哪张图、轮播八格放什么、
景点卡从哪一级取,全部在 `work/<CODE>/editorial.json` 里,由 `lib/editorial.py`
读取和校验(issue #4)。这里只剩「怎么选」,不剩「选了什么」——所以跑一本新册子
不再需要改这个文件。哪些产品存在,也由「谁有 editorial.json」决定。

Days the token matcher cannot resolve are each decided by looking, and the
reason is written next to the pick in that product's `editorial.json`. The
standing rule, set by the Planner on 2026-08-12: where no photograph of the
landmark exists that is actually of that place, show a compliant picture of
the day's own city or region rather than a lookalike from somewhere else.
Stock had real ice caves (Siberia) and real volcanoes (Etna, Nicaragua) for
WBCHET days 4 and 7 — right subject, wrong continent, and a page selling this
trip cannot carry them. Stock is never auto-picked.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import editorial
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
    """Resolve a product's `trip_picks` into a pool `assign_trip_photos` draws from.

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
            raise SystemExit(
                f"{code} trip_picks: 景点卡只支持 commons / stock,收到 {kind!r}")
        block, n = ref
        blk = table.get(block)
        row = next((c for c in (blk or {}).get("candidates", []) if c["n"] == n), None)
        if row is None:
            raise SystemExit(
                f"{code} trip_picks: 指向 {kind} {block}#{n},"
                f"没找到 —— {hint}")
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
                        f"{code} section_overrides.{key}: stock {block}#{n} "
                        f"不在 candidates.json 里 —— "
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
                    raise SystemExit(f"{code} section_overrides.{key}: catalogue image "
                                     f"{ref} not in catalogue.json")
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
                        f"{code} section_overrides.{key}: commons {block}#{n} "
                        f"不在 commons.json 里 —— "
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
                    raise SystemExit(f"{code} carousel[{i}]: {block} not in catalogue.json")
                pull_catalogue(code, [row])
                plan.placements.append(Placement(
                    slot="carousel", position=i, origin="catalogue",
                    subject=row["alt"], source_ref=row["tour"],
                    src_path=row["path"], credit="webuytravel.sg", note=head + note))
                continue
            row = next((c for c in (stock or {}).get(block, {}).get("candidates", [])
                        if c["n"] == n), None)
            if row is None:
                raise SystemExit(
                    f"{code} carousel[{i}]: {block}#{n} not in candidates.json")
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


def run(code: str, work: Path = WORK) -> tuple[ImagePlan, list]:
    """一个产品从编辑决策走到成片的 plan,不含 materialise。

    拆出来是为了让 `tools/verify_equivalence.py` 能在**不落地图片**的前提下
    跑完整条决策链 —— 迁移前后 17 个产品的 plan 逐字节比对靠的就是这个口子
    (issue #4 Done When 第 1 条)。落地那一步在下面的 `__main__` 里,和以前一样。
    """
    doc = editorial.load(code, work)
    tours = doc["catalogue_tours"]
    plan = compose(code, doc["region"], tours, editorial.section_overrides(doc))
    stock = json.loads((work / code / "candidates.json").read_text("utf-8")) \
        if (work / code / "candidates.json").exists() else {}
    fill_carousel(plan, code, tours, picks=editorial.carousel(doc), stock=stock)
    removed = dedupe(plan, cross_slot=bool(tours))
    # 景点卡这一层。放在 dedupe 之后:它复用的是去重之后真正留下的那些图,
    # 而不是可能马上被删掉的。也放在 materialise 之前,这样 trip 槽和别的槽
    # 一起编码,不会出现一半产物的 out/ 目录。
    itin = json.loads((work / code / "itinerary.json").read_text("utf-8"))
    assign_trip_photos(plan, itin["sections"], score, MATCH_FLOOR,
                       extra=trip_pool(code, editorial.trip_picks(doc)))
    return plan, removed


if __name__ == "__main__":
    # 只跑指定的产品。默认全跑会把已经审过的三个产品的 plan.json 连同
    # 它们的图一起重新生成,那是不必要的网络往返,也会让已签字的配图漂移。
    only = set(sys.argv[1:])
    # 产品清单以前是源码里的 `PRODUCTS`,现在是「谁有 editorial.json 谁就是
    # 一个产品」。顺序从「写进源码的顺序」变成字典序,产出不受影响:每个产品
    # 各写各的 work/<CODE>/plan.json,产品之间没有共享状态。
    for code in editorial.codes(WORK):
        if only and code not in only:
            continue
        plan, removed = run(code)
        # 上一轮的产物,在这一轮覆盖它们之前先记下来。`materialise` 返回的是
        # plan 本身(见 lib/image_plan.py 的签名),不是清理清单——把它的返回值
        # 当清单用,下面的 len()/join() 必炸,而且炸在 GAP 那一圈之前,正好把
        # 人工闸门要看的那几行吞掉。清理是这里的事,就在这里做。
        out_dir = WORK / code / "out"
        before = {p.name for p in out_dir.glob("*")} if out_dir.exists() else set()
        materialise(plan, out_dir)
        kept = {Path(p.out_path).name for p in plan.placements if p.out_path}
        stale = sorted(before - kept)
        for name_ in stale:
            (out_dir / name_).unlink()
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
        # 上一轮生成、这一轮已经不在 plan 里的图。点名,不只报数:留下来的
        # 那几张恰恰是被判定为错图删掉的,而按文件名通配去取上传清单看不出
        # 区别(DESIGN 6.12)。
        if stale:
            print(f"    CLEANED out/: {len(stale)} 个文件不在本次 plan 中,已删除 "
                  f"— {', '.join(stale)}")
        for g in plan.gaps:
            print(f"    GAP day {g.position}: {', '.join(g.subjects)[:70]}")
