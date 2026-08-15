"""Decide which photo goes in which Skybear slot, then produce the files.

The plan is the contract between the thinking part of the pipeline (an agent
looking at photos and deciding what they show) and the mechanical part
(cropping, encoding, and driving the Skybear UI). It is a plain dataclass
tree that serialises to JSON, so a run can be reviewed, corrected and
re-materialised without re-deciding anything.

Flow, per tour:

1. `pdf_images.extract()`      — pull and grade the brochure's own photos.
2. *agent looks at them*       — assigns `subject` and `day` to each.
3. `build()`                   — fills slots PDF-first, reports what's short.
4. `photo_source.search()`     — candidates for the gaps.
5. *agent looks at them*       — picks one per gap.
6. `materialise()`             — crop/resize/encode every pick to spec.
7. `render_preview()`          — a page the Planner signs off before upload.

Slot priority follows the brief: brochure photos first, web second. The one
exception is the hero — carousel position 0 — which is described below.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from .image_norm import normalise
from .image_spec import (CAROUSEL, SECTION, THUMBNAIL, TRIP, SlotSpec,
                         crop_window)
from .pdf_images import PdfImage, PdfImageSet


@dataclass
class DaySection:
    """One itinerary day, in the shape `pdf_extract_prompt.md` already emits."""

    sort_num: int  # 0-based; DAY 1 is sort_num 0
    title_en: str = ""
    location_en: str = ""
    landmarks: list[str] = field(default_factory=list)

    @property
    def day(self) -> int:
        return self.sort_num + 1

    @property
    def search_subjects(self) -> list[str]:
        """What to look for when this day needs a web photo."""
        return self.landmarks or ([self.location_en] if self.location_en else [])


@dataclass
class Placement:
    """One image, bound to one slot."""

    slot: str  # carousel | thumbnail | route_map | section | trip
    position: int  # order within the slot; day number for sections and trips
    origin: str  # pdf | web
    subject: str
    source_ref: str  # "p3 #1" for PDF, or the candidate URL for web
    src_path: str = ""  # local file before normalising
    out_path: str = ""  # normalised file, filled by materialise()
    # `trip` only: which landmark card on that day, 0-based in document order.
    # A day has one section grid but several trip cards, so position alone
    # stops being a unique address once this slot exists.
    trip_index: int | None = None
    upscale: float = 0.0
    bytes: int = 0
    credit: str = ""
    license: str = ""
    note: str = ""


@dataclass
class Gap:
    """A slot the brochure could not fill, with what to search for."""

    slot: str
    position: int
    subjects: list[str]
    reason: str


# 三种「这天没有配图」的成因,处理办法完全不同,所以不能合并成一句话:
#   NO_MATCH   有 photo_subject,四级图源都没给出可用的实拍 → 换图源/自备照片
#   NO_SUBJECT 有景点条目,但一个 photo_subject 都没写 → 从来没搜过,补 subject 就能搜
#   NO_ITEMS   连景点条目都没有,纯抵离日 → 线上参考产品的最后一天也是空的
GAP_NO_MATCH = "no source matched this day"
GAP_NO_SUBJECT = ("day has trip items but not one carries photo_subject "
                  "— nothing was ever searched for")
GAP_NO_ITEMS = "no trip items — arrival/departure transit day"


def section_gap(day: int, has_items: bool, subjects: list[str],
                fallback: list[str]) -> Gap:
    """The Gap to log when a day ends with zero section photos.

    Always returns one. The bug this replaces was a `placed == 0 and subjects`
    guard in `bin/compose.py`: a day whose trip items carry no `photo_subject`
    produced neither a placement nor a gap, so `bin/review_page.py` — the human
    sign-off gate — had nothing to render for it and the day shipped blank.
    WBCHET D1, WBCURC D1/D12/D13 and WBCKWE D9 all reached production that way
    (2026-08-13). See docs/DESIGN.md 6.11.

    `fallback` is the day's own city: not a photo, just the last remaining
    thing a human could search on once the itinerary offered nothing.
    """
    if subjects:
        reason = GAP_NO_MATCH
    elif has_items:
        reason = GAP_NO_SUBJECT
    else:
        reason = GAP_NO_ITEMS
    return Gap(slot="section", position=day,
               subjects=subjects or fallback, reason=reason)


@dataclass
class ImagePlan:
    type_code: str
    region: str
    placements: list[Placement] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)

    def of(self, slot: str) -> list[Placement]:
        return [p for p in self.placements if p.slot == slot]

    def to_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))
        return path


def _ref(img: PdfImage) -> str:
    return f"p{img.page} #{img.index} ({img.width}x{img.height})"


def build(
    type_code: str,
    region: str,
    pdf_set: PdfImageSet,
    sections: list[DaySection],
    carousel_target: int = 8,
) -> ImagePlan:
    """Assign brochure photos to slots and record what's still missing.

    Expects `pdf_set` images to already carry `subject` and `day` from the
    agent's look — an unassigned photo can still fill the carousel (order
    there is editorial, not factual) but never a day's grid, because putting
    a Turpan photo under "DAY 6 Kuitun" is exactly the failure the caption
    trap produces.

    **The hero is deliberately not PDF-first.** Carousel position 0 is
    cropped into a wide band and rendered at ~1600px on the product page.
    Brochure photos land at 719–860px before upscaling, so the hero is left
    as a gap for the web source to fill sharply. Every other carousel
    position prefers the brochure.
    """
    plan = ImagePlan(type_code=type_code, region=region)

    all_subjects = list(dict.fromkeys(
        s for sec in sections for s in sec.search_subjects
    ))
    plan.gaps.append(Gap(
        slot="carousel", position=0,
        subjects=all_subjects[:6],
        reason="hero renders ~1600px wide; brochure photos top out at ~860px",
    ))

    # Carousel: brochure photos that clear the carousel floor, best first.
    carousel_pool = sorted(pdf_set.hero_grade, key=lambda i: -i.crop_width(CAROUSEL))
    for position, img in enumerate(carousel_pool[: carousel_target - 1], start=1):
        plan.placements.append(Placement(
            slot="carousel", position=position, origin="pdf",
            subject=img.subject or "(unidentified)", source_ref=_ref(img),
            src_path=str(img.path),
            note="" if img.subject else "subject not assigned — editorial order only",
        ))

    still_needed = carousel_target - 1 - len(carousel_pool)
    for position in range(len(carousel_pool) + 1, carousel_target):
        if still_needed <= 0:
            break
        plan.gaps.append(Gap(
            slot="carousel", position=position,
            subjects=all_subjects, reason="brochure ran out of carousel-grade photos",
        ))

    # Thumbnail: reuse the sharpest carousel-grade brochure photo rather
    # than sourcing a second web image for a tile that renders at ~400px.
    if carousel_pool:
        best = carousel_pool[0]
        plan.placements.append(Placement(
            slot="thumbnail", position=0, origin="pdf",
            subject=best.subject or "(unidentified)", source_ref=_ref(best),
            src_path=str(best.path), note="reuses the sharpest brochure photo",
        ))
    else:
        plan.gaps.append(Gap("thumbnail", 0, all_subjects[:4],
                             "no carousel-grade brochure photo available"))

    # Route map: the brochure's own schematic, straight into route_map_url.
    for img in pdf_set.route_maps[:1]:
        plan.placements.append(Placement(
            slot="route_map", position=0, origin="pdf",
            subject="itinerary route map", source_ref=_ref(img),
            src_path=str(img.path),
            note="brochure schematic — not normalised, uploaded as-is",
        ))

    # Per-day grids: only photos the agent actually tied to that day.
    by_day: dict[int, list[PdfImage]] = {}
    for img in pdf_set.usable:
        if img.day:
            by_day.setdefault(img.day, []).append(img)

    # A brochure photo the agent DID tie to this day but which is too small
    # to ship — worth saying so, because "no photo found" and "found one,
    # it's 611px" call for different fixes.
    too_small_by_day: dict[int, list[PdfImage]] = {}
    for img in pdf_set.undersized:
        if img.day:
            too_small_by_day.setdefault(img.day, []).append(img)

    for section in sections:
        for img in by_day.get(section.day, []):
            plan.placements.append(Placement(
                slot="section", position=section.day, origin="pdf",
                subject=img.subject, source_ref=_ref(img), src_path=str(img.path),
            ))
        if by_day.get(section.day):
            continue
        if not section.search_subjects:
            # Pure transit — an arrival or departure day with nothing to
            # show. Skybear renders the section fine without a grid.
            continue
        undersized = too_small_by_day.get(section.day)
        if undersized:
            sizes = ", ".join(f"{i.width}x{i.height}" for i in undersized)
            reason = (f"brochure has {undersized[0].subject or 'a photo'} for this day "
                      f"but it is only {sizes} — under the {SECTION.min_source_width}px floor")
        else:
            reason = f"no brochure photo identified for DAY {section.day}"
        plan.gaps.append(Gap(
            slot="section", position=section.day,
            subjects=section.search_subjects, reason=reason,
        ))

    return plan


_CONTENT_CACHE: dict[str, str] = {}


def _content_key(path: str) -> str:
    """sha1 of the bytes, so two filenames holding one photo collapse.

    Falls back to the path when the file cannot be read — a missing source
    is `materialise`'s problem to shout about, not this function's.
    """
    if path in _CONTENT_CACHE:
        return _CONTENT_CACHE[path]
    try:
        key = hashlib.sha1(Path(path).read_bytes()).hexdigest()
    except Exception:                                      # noqa: BLE001
        key = path
    _CONTENT_CACHE[path] = key
    return key


def assign_trip_photos(plan: ImagePlan, sections: list[dict],
                       score, floor: float, per_item: int = 2,
                       max_reuse: int = 1,
                       extra: list[Placement] | None = None) -> ImagePlan:
    """Hang photos the plan already holds onto the landmark cards.

    The live reference product renders three small images under every
    landmark card (`tours/112` carries 68 of them); this project shipped all
    five products with that layer empty. Roughly half the gap closes for
    free, because a day's section photo usually *is* a photo of one of that
    day's landmarks — the Yungang Grottoes tile and the "Yungang Grottoes"
    trip card want the same picture. Measured across the five products,
    71 of 126 cards match something already in the plan.

    Nothing new is sourced and nothing is re-judged: the pool is only
    placements a person already signed off for the section and carousel
    slots, so this cannot introduce a wrong-place photo that the review gate
    has not already seen.

    **Two things a card must never show**, both found on the live products
    after the first upload (2026-08-14) and both produced by this function:

    * **the same photo as its own day's section tile.** 64 of the first 154
      trip photos were byte-identical to the section image directly above
      them, because section placements are in the pool and scored highest —
      they are, after all, photos of that day. On the page it reads as the
      picture having been pasted twice.
    * **the same photo twice anywhere in the trip layer.** 28 repeated
      within a single day.

    So a day's own section sources are excluded from that day's pool, and
    `max_reuse` counts uses *within this layer* — 1 by default, meaning a
    file appears on at most one card in the whole product. Raising it above
    1 brings the repeats back; it is a knob for coverage, not a default.

    `extra` carries photos approved for the cards but deliberately kept out
    of the section grid. The three live Inner Mongolia products put every
    photo on the landmark cards and leave `Section Photos` empty
    (`docs/DESIGN.md` 1.1), so a day with five good Commons photos wants one
    section tile and four cards, not five section tiles. Entries here are as
    hand-picked as `OVERRIDES` — they never enter the plan on their own,
    only through a card that matches them.
    """
    # `extra` 排在前面,不是后面。下面的排序按分数,而**同一个块里的候选分数
    # 完全相同**(score 比的是块的 subject,不是具体那张图),Python 的排序又是
    # 稳定的——所以池子的顺序就是同分时的胜负。原来 section 在前,结果是:
    # 某一天的 section 图会被**别的天**的卡抢走,而这张卡明明有一条专门为它
    # 挑的 extra。WBYNG 上一次跑出来三处:D2 怒江大峡谷那张卡吃掉了 D3 和 D4
    # 的天头图,D6 飞来寺观景台吃掉了 D5 的天头图(于是观景台卡上是一座白塔,
    # 而我为它挑的梅里全景根本没进去)。
    #
    # 两个后果都要修。一是页面上同一张照片出现两次(6.06 业务同事提的正是
    # 「重复」);二是**手挑的条目被静默顶掉**,而摘要里看不出来——6.9 记的
    # 静默降级就是这一类。extra 的定义本来就是「为景点卡挑的」,同分时它该赢。
    pool = list(extra or ())
    pool += [p for p in plan.placements if p.slot in ("section", "carousel")]
    used: dict[str, int] = {}

    # 按**内容**去重,不按路径。08-14 第一次修完之后 WBCHET 第 6 天的卡 2 和卡 3
    # 仍然是同一张图:Commons 的 `d06_yungang_grottoes_datong` 和
    # `d06_yungang_grottoes_buddha_statues` 两个块下载到了同一张照片,
    # 存成了两个文件名。按 src_path 去重看不出来,按 sha1 一眼就看出来。
    ident = _content_key

    # 当天 section 用掉的源文件,那天的卡一律不许再用。
    section_src: dict[int, set[str]] = {}
    for p in plan.placements:
        if p.slot == "section":
            section_src.setdefault(p.position, set()).add(ident(p.src_path))

    for section in sections:
        day = section["day"]
        blocked = section_src.get(day, set())
        for index, item in enumerate(section.get("trip_items", [])):
            subject = item.get("photo_subject") or item["title"]["en"]
            ranked = sorted(
                ((score(subject, p.subject), p) for p in pool),
                key=lambda pair: -pair[0])
            taken = 0
            for value, placement in ranked:
                if taken >= per_item or value < floor:
                    break
                key = ident(placement.src_path)
                if key in blocked:
                    continue
                if used.get(key, 0) >= max_reuse:
                    continue
                used[key] = used.get(key, 0) + 1
                plan.placements.append(Placement(
                    slot="trip", position=day, trip_index=index,
                    origin=placement.origin, subject=placement.subject,
                    source_ref=placement.source_ref,
                    src_path=placement.src_path,
                    credit=placement.credit, license=placement.license,
                    note=f"reused from {placement.slot}#{placement.position}"))
                taken += 1
    return plan


def compose_carousel(plan: ImagePlan, order: list[str],
                     target: int = 8) -> ImagePlan:
    """Rebuild the carousel from images the plan already holds.

    Run this after the day gaps are filled. A carousel is a highlights reel,
    not a separate shoot — the live catalogue reuses day photos in it — so
    sourcing distinct carousel images would mean paying twice for the same
    landmarks and would make the two galleries disagree.

    `order` is the agent's editorial sequence, given as source paths so a
    day holding two photos (Sayram Lake *and* Guozigou Bridge both fall on
    WBCURC day 7) stays addressable. Position 0 becomes the hero, so put a
    wide, sharp, instantly-readable shot there.
    """
    pool = {p.src_path: p for p in plan.placements
            if p.slot in ("section", "carousel")}
    plan.placements = [p for p in plan.placements if p.slot != "carousel"]
    plan.gaps = [g for g in plan.gaps if g.slot != "carousel"]

    for position, key in enumerate(order[:target]):
        source = pool.get(str(key))
        if source is None:
            continue
        # A photo good enough for a section tile is not automatically good
        # enough for the hero — the tile renders at a few hundred pixels,
        # the hero at ~1600. Flag rather than block: the reviewer decides.
        note = "hero" if position == 0 else ""
        with Image.open(source.src_path) as probe:
            crop = crop_window(*probe.size, CAROUSEL.aspect)[0]
        if crop < CAROUSEL.min_source_width:
            note = (note + f" | source only {crop}px wide for a "
                           f"{CAROUSEL.width}px slot").strip(" |")

        plan.placements.append(Placement(
            slot="carousel", position=position, origin=source.origin,
            subject=source.subject, source_ref=source.source_ref,
            src_path=source.src_path, credit=source.credit,
            license=source.license, note=note,
        ))

    shortfall = target - len(plan.of("carousel"))
    if shortfall > 0:
        plan.gaps.append(Gap(
            slot="carousel", position=len(plan.of("carousel")),
            subjects=[], reason=f"{shortfall} carousel slots still empty",
        ))
    return plan


def add(plan: ImagePlan, slot: str, position: int, *, origin: str, subject: str,
        source_ref: str, local: str | Path, credit: str = "", license: str = "",
        note: str = "") -> ImagePlan:
    """Record an agent-chosen image against a gap, and close the gap."""
    plan.placements.append(Placement(
        slot=slot, position=position, origin=origin, subject=subject,
        source_ref=source_ref, src_path=str(local), credit=credit,
        license=license, note=note,
    ))
    plan.gaps = [g for g in plan.gaps
                 if not (g.slot == slot and g.position == position)]
    return plan


def add_web(plan: ImagePlan, slot: str, position: int, *, subject: str,
            url: str, local: str | Path, credit: str = "",
            license: str = "") -> ImagePlan:
    """Record an agent-chosen web photo against a gap. The common case."""
    return add(plan, slot, position, origin="web", subject=subject,
               source_ref=url, local=local, credit=credit, license=license)


def accept_undersized(plan: ImagePlan, image: PdfImage, day: int) -> ImagePlan:
    """Ship a brochure photo the size gate would otherwise reject.

    An escape hatch for the case where the deck holds the *right* photo of a
    day's headline attraction and nothing else does. WBCKWE day 8 is the
    example: Tongren Grand Canyon at 744×385 crops to 513px, under the 632
    floor, and no catalogue or stock source carries that gorge at all — so
    the choice is a soft-but-correct photo or a day with no picture of the
    thing it is selling.

    Deliberately explicit and deliberately noisy: it takes a named image,
    and the note it writes shows up on the review page so the decision is
    the reviewer's to overturn.
    """
    crop = image.crop_width(SECTION)
    return add(plan, "section", day, origin="pdf", subject=image.subject,
               source_ref=_ref(image), local=image.path,
               credit="brochure", note=(
                   f"below the {SECTION.min_source_width}px floor "
                   f"({crop}px crop) — accepted because no other source "
                   f"carries this landmark"))


def _dhash(path: str | Path, size: int = 16) -> np.ndarray:
    """Perceptual hash — a gradient signature that survives re-cropping.

    Two crops of the same photograph, or the same photo at two sizes, land
    within a few bits of each other; genuinely different photos of the same
    landmark do not.
    """
    with Image.open(path) as im:
        grey = im.convert("L").resize((size + 1, size), Image.LANCZOS)
    pixels = np.asarray(grey, dtype=np.int16)
    return (pixels[:, 1:] > pixels[:, :-1]).flatten()


# Bits of difference below which two images read as the same picture. 16×16
# dhash gives 240 bits; identical files score 0, re-crops of one photo score
# 1–4, and distinct photos of one landmark measured 40+ across the launch
# samples. 12 sits well inside that gap.
DUPLICATE_BITS = 12


def dedupe(plan: ImagePlan, *, cross_slot: bool = True,
           slot_priority: tuple[str, ...] =
           ("section", "route_map", "thumbnail", "carousel")) -> list[str]:
    """Drop repeats. Returns a human-readable list of what went.

    Two failure modes, both of which shipped in the first launch build and
    both of which a reviewer spots instantly:

    * **The same file in two slots.** The carousel was composed out of the
      day grids, so every carousel image was byte-identical to a section
      image. The live catalogue does not do this — its Desktop Display
      Images and its Section Photos are different pictures — and a customer
      scrolling one page sees the repeat.
    * **The same subject twice in one day.** Pulling every catalogue match
      for a landmark put three Maling River Canyon shots on day 5.

    Slot priority decides who keeps a contested image, and **sections win**.
    A day with no picture of the thing it is selling is a worse page than a
    carousel one slide shorter, and the carousel can always be refilled from
    the leftover pool — a specific landmark on a specific day cannot.

    Set `cross_slot=False` when there is no leftover pool to refill from.
    WBCHET is the case: nothing published covers Shanxi, so its only images
    are the four in the brochure plus a handful off Commons. Enforcing
    cross-slot uniqueness there empties the carousel down to one slide,
    which is worse than a carousel that reprises the day photos. Within-day
    repeats are still removed either way — three shots of one waterfall side
    by side is the failure a reviewer actually notices.
    """
    order = {slot: i for i, slot in enumerate(slot_priority)}
    ranked = sorted(
        [p for p in plan.placements if p.src_path],
        key=lambda p: (order.get(p.slot, 99), p.position),
    )

    removed: list[str] = []
    kept: list[tuple[Placement, np.ndarray]] = []
    subjects_per_day: dict[tuple[str, int], set[str]] = {}

    for placement in ranked:
        try:
            signature = _dhash(placement.src_path)
        except (OSError, ValueError):
            kept.append((placement, None))
            continue

        # The list thumbnail is *deliberately* the carousel hero — that is what
        # `fill_carousel` builds it from, and the live catalogue does the same.
        # Cross-slot dedupe used to read that intent as an accident: thumbnail
        # outranks carousel in `slot_priority`, so it kept the thumbnail and
        # deleted slide 0. The carousel then renumbered, promoting whatever was
        # second, and `fill_carousel`'s leftover pool refilled the tail — so the
        # product shipped with one slide fewer and a hero that no longer matched
        # its thumbnail. WBCKWE (408) and WBCURC (409) both went out this way on
        # 2026-08-13; WBCHET only escaped because it has no catalogue pool and
        # therefore ran with cross_slot=False.
        exempt = {"thumbnail", "carousel"}
        twin = next((k for k, sig in kept
                     if sig is not None
                     and (cross_slot or k.slot == placement.slot)
                     and not (k.slot != placement.slot
                              and {k.slot, placement.slot} == exempt)
                     and int((sig != signature).sum()) <= DUPLICATE_BITS), None)
        if twin is not None:
            removed.append(f"{placement.slot}#{placement.position} "
                           f"{placement.subject} — same picture as "
                           f"{twin.slot}#{twin.position}")
            continue

        key = (placement.slot, placement.position)
        seen = subjects_per_day.setdefault(key, set())
        if placement.subject and placement.subject in seen:
            removed.append(f"{placement.slot}#{placement.position} "
                           f"{placement.subject} — subject already shown here")
            continue
        seen.add(placement.subject)
        kept.append((placement, signature))

    keep_ids = {id(p) for p, _ in kept}
    plan.placements = [p for p in plan.placements
                       if not p.src_path or id(p) in keep_ids]

    # Carousel positions must stay contiguous — position 0 is the hero.
    for i, placement in enumerate(sorted(plan.of("carousel"),
                                         key=lambda p: p.position)):
        placement.position = i
    return removed


def materialise(plan: ImagePlan, out_dir: str | Path) -> ImagePlan:
    """Crop, resize and encode every placement to its slot's standard.

    The route map is copied rather than cropped — it is a diagram with text
    on it, and a 4:3 crop would slice the legend off.

    **A source that is absent, or a placement that never got a path, aborts
    the run.** This used to degrade quietly — a missing file only added
    "source file missing" to the placement's note, and an unresolved
    `src_path` was skipped outright — so `compose.py` printed its usual
    summary line, exited 0, and the day simply had no photo. That is the
    worst possible shape for this failure: every downstream step keeps
    working, and the gap only shows up on a customer-facing page.

    Both cases are wiring bugs, not data conditions:

    * an empty `src_path` means the catalogue resolution pass never filled
      it in, which is a mismatch between `chosen_cat` and the placements
      waiting on it;
    * a path that does not exist means an `OVERRIDES` entry points at
      something that is gone. Everything under `work/**/cand/`, `cat/` and
      `raw/` is gitignored, so a fresh checkout has none of it until the
      fetch steps have run — a repo-relative path is not the same as a
      path that is present.

    Raising here also means `work/<CODE>/out/` is never left half-written:
    the check runs before anything is encoded, so a failed run leaves no
    partial directory for a later step to mistake for a complete one.
    """
    out_dir = Path(out_dir)
    slots: dict[str, SlotSpec] = {
        "carousel": CAROUSEL, "thumbnail": THUMBNAIL, "section": SECTION,
        "trip": TRIP,
    }

    missing = [
        f"  {p.slot}#{p.position} {p.subject or '(no subject)'} — "
        + (p.src_path if p.src_path else "no source path was ever resolved")
        for p in plan.placements
        if not p.src_path or not Path(p.src_path).exists()
    ]
    if missing:
        raise FileNotFoundError(
            f"{plan.type_code}: {len(missing)} placement(s) have no usable "
            f"source, refusing to materialise:\n" + "\n".join(missing)
            + "\n\nWorking artefacts (work/**/cand/, cat/, raw/) are gitignored — "
              "in a fresh checkout they exist only after the fetch steps have run.")

    for placement in plan.placements:
        src = Path(placement.src_path)

        stem = f"{placement.slot}_{placement.position:02d}"
        if placement.slot == "trip":
            stem = f"trip_{placement.position:02d}_{placement.trip_index or 0:02d}"
        if placement.slot == "route_map":
            dest = out_dir / f"{stem}{src.suffix}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
            placement.out_path = str(dest)
            placement.bytes = dest.stat().st_size
            placement.upscale = 1.0
            continue

        spec = slots[placement.slot]
        # Several photos can share one day's grid, so disambiguate.
        existing = len([p for p in plan.placements
                        if p.slot == placement.slot
                        and p.position == placement.position
                        and p.trip_index == placement.trip_index
                        and p.out_path])
        dest = out_dir / f"{stem}_{existing}.jpg"
        result = normalise(src, dest, spec)
        placement.out_path = str(result.path)
        placement.upscale = result.upscale
        placement.bytes = result.bytes
        if result.is_soft:
            placement.note = (placement.note
                              + f" | upscaled {result.upscale:.2f}×").strip(" |")

    return plan
