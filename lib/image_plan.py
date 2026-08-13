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

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from .image_norm import normalise
from .image_spec import CAROUSEL, SECTION, THUMBNAIL, SlotSpec, crop_window
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

    slot: str  # carousel | thumbnail | route_map | section
    position: int  # order within the slot; day number for sections
    origin: str  # pdf | web
    subject: str
    source_ref: str  # "p3 #1" for PDF, or the candidate URL for web
    src_path: str = ""  # local file before normalising
    out_path: str = ""  # normalised file, filled by materialise()
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
    """
    out_dir = Path(out_dir)
    slots: dict[str, SlotSpec] = {
        "carousel": CAROUSEL, "thumbnail": THUMBNAIL, "section": SECTION,
    }

    for placement in plan.placements:
        if not placement.src_path:
            continue
        src = Path(placement.src_path)
        if not src.exists():
            placement.note = (placement.note + " | source file missing").strip(" |")
            continue

        stem = f"{placement.slot}_{placement.position:02d}"
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
