"""Webuy house image standard — the single source of truth for every slot.

The numbers here are **measured from live production**, not from the Skybear
admin UI hints. The Edit Display Detail page suggests "1920×1080 (16:9)" for
Image Carousel, but no shipped product follows it. Sampling the OSS originals
behind `webuytravel.sg/tours/115` (9D8N Guizhou, a direct style peer of the
tours we upload) gave:

    1080×1440 (3:4)  ×6      1440×1080 (4:3)  ×3
    1080×1923 (9:16) ×3      1012× 847 (thumb)
    200–900 KB JPEG, served from prod-webuysg.oss.webuy.ren/travel-video/

The mixed ratios initially read as inconsistency. They are not. Opening Edit
Display Detail on a live product (2026-08-06) showed the carousel is **two
slots, not one**:

    Mobile Display Image    1080×1440 … 1080×1620   portrait, ar 0.66–0.75
    Desktop Display Image   1012×847 … 1732×1080    landscape, ar 1.19–1.60
    List Thumbneil          554×400                 landscape, ar 1.38

So every image ships twice, cropped for the device it will be seen on. The
Phase 0 field inventory predates this — it lists a single "Image Carousel"
mapped to `wt_travel_image (image_type=1)`.

Decision (2026-08-05/06, with wangchengtai): one ratio per slot, cropped
from the original each time rather than re-cropping the landscape version —
**4:3 landscape at 1440×1080** for desktop, **3:4 portrait at 1080×1440**
for mobile.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SlotSpec:
    """Target geometry + encoding for one Skybear image slot."""

    name: str
    width: int
    height: int
    max_bytes: int
    jpeg_quality: int
    max_count: int
    max_upscale: float

    @property
    def aspect(self) -> float:
        return self.width / self.height

    @property
    def min_source_width(self) -> int:
        """Narrowest crop window that can fill this slot without going soft.

        Note this is measured on the **cropped** window, not the raw file.
        Cropping a 942×579 brochure photo to 4:3 leaves only 772px of width
        to work with — the raw long edge flatters it.
        """
        return int(round(self.width / self.max_upscale))


# Skybear caps every upload at 6MB; we aim well under so OSS re-encode and
# the `x-oss-process` resize chain never hit the ceiling.
_MAX_BYTES = 5 * 1024 * 1024

# Image Carousel → wt_travel_image (image_type=1). The first image becomes
# the product-page hero, rendered ~1600px wide and cropped to a ~3:1 band.
#
# The 2.0 ceiling is measured, not assumed. A 1.65 ceiling was tried first
# and rejected zero-for-three across the launch brochures — every brochure
# photo lands at a 719–860px 4:3 crop — which would have handed the whole
# carousel to stock imagery. Rendering the worst case (a 733×704 Huangguoshu
# Falls shot, 1.97×) at full size showed no objectionable softening, and the
# live catalogue's own heroes are already cropped out of ~1080px-wide
# regions, so this bar is at or above what ships today.
CAROUSEL = SlotSpec("carousel", 1440, 1080, _MAX_BYTES, 86, 10, max_upscale=2.0)

# Mobile Display Image — the phone half of the carousel. Portrait, because
# the phone layout gives it the full viewport height; feeding it the
# landscape crop would letterbox every slide. Cropped from the original
# source, never from the desktop JPEG, or it would be a 4:3 frame squeezed
# into 3:4 with most of the subject gone.
CAROUSEL_MOBILE = SlotSpec("carousel_mobile", 1080, 1440, _MAX_BYTES, 86, 10,
                           max_upscale=2.0)

# List Thumbnail → wt_travel.list_thumbneil (sic — the column really is
# misspelled). Live thumb is 554×400 ≈ 1.38, so 4:3 is close and lets the
# thumbnail reuse a desktop carousel frame.
THUMBNAIL = SlotSpec("thumbnail", 1440, 1080, _MAX_BYTES, 86, 1, max_upscale=2.0)

# Per-day Image Grid → wt_travel_section_image. Rendered as small tiles, so
# a softer source is invisible here. The looser ceiling is deliberate: it is
# what lets a 725px brochure photo still serve its own day instead of being
# replaced by stock, which is the whole point of PDF-first.
SECTION = SlotSpec("section", 1200, 900, _MAX_BYTES, 84, 10, max_upscale=1.90)

# Trip Photos → wt_travel_trip_image, the 3-up strip under each landmark
# card. Measured on the live reference product `tours/112` (2026-08-14,
# viewport 1291×707), because the numbers above it were assumed and this one
# should not be:
#
#   hero band          1283×460   ×1
#   per-day section    220×165    ×9      ← SECTION ships 1200px for this
#   trip photo tile    89×89      ×68     ← this slot
#
# 89px would be an absurd target, and it is not the real one: the tiles are
# `cursor: zoom-in` and open a lightbox. In the lightbox the image renders
# **535×643** off a 1080×1297 source, and a taller viewport pushes that to
# roughly 750px. So the lightbox sets the floor, not the tile.
#
# 1080 on the long edge is also exactly what the live catalogue already
# ships (`lib/catalogue_source.py` — "1080-class on the long edge, straight
# off the OSS bucket"), so this target is the house standard rather than a
# new bar. The 2.2 ceiling is looser than SECTION's 1.90 on purpose: a
# 492px brochure crop lands at 2.2× here and still renders at or above the
# 535px lightbox size, and letting those photos through is the entire
# reason this spec exists — see `docs/DESIGN.md` 3.6.1 for the seven real
# photos that the SECTION-derived floor was throwing away.
TRIP = SlotSpec("trip", 1080, 810, _MAX_BYTES, 84, 10, max_upscale=2.2)

# Cover Video Asset → wt_travel.video_cover_url. The one slot that is
# genuinely portrait (UI hint 986×1752 ≈ 9:16) — do NOT 4:3 this one.
COVER_PORTRAIT = SlotSpec("cover_portrait", 986, 1752, _MAX_BYTES, 86, 1, max_upscale=1.65)


# --- quality gates ----------------------------------------------------

# Below this on either edge it is furniture, not a photo — the brochures
# embed 67×64 / 87×81 / 160×160 icons and 73×70 bullet glyphs.
MIN_ANY_EDGE = 300

# Page-wide banners and rule lines. Measured: 1562×386 (4.05) and 1294×320
# (4.04) are decorative headers in all three samples.
MAX_ASPECT = 3.0
MIN_ASPECT = 1 / 3.0

# Smallest 4:3 crop window worth keeping at all. Under this the photo can't
# even serve a section tile, so the day goes to the web fallback.
MIN_PDF_CROP_WIDTH = SECTION.min_source_width  # 632px

# …but "can't serve a section tile" is not the same as "unusable", and for
# five years' worth of brochures that difference was being thrown away. Of
# the 61 rasters across the five launch brochures, 7 are real photographs of
# real stops on the itinerary — 苗族歌舞, 小七孔撑船, 千户苗寨吊脚楼,
# 新疆民族歌舞, 卡拉麦里的鹅喉羚 — rejected only for landing at a 420–610px
# 4:3 crop against the 632 line above. That line comes from SECTION's 1200px
# target, and SECTION renders at 220px on the page.
#
# A trip photo is a 89px tile that opens a ~535–750px lightbox, so it has
# its own, lower floor. Do NOT solve this by lowering MIN_PDF_CROP_WIDTH:
# SECTION is the only per-day image that ever appears large, and dropping
# its floor trades a visible slot for an invisible one.
MIN_TRIP_CROP_WIDTH = TRIP.min_source_width    # 491px


def crop_window(width: int, height: int, aspect: float) -> tuple[int, int]:
    """Largest (w, h) of ratio `aspect` that fits inside `width`×`height`.

    This — not the raw file size — is the number that decides whether a
    source can fill a slot. A 942×579 photo has a healthy-looking 942px
    long edge, but the widest 4:3 window inside it is only 772px, because
    the crop is bounded by the 579px height.
    """
    if width / height > aspect:  # too wide → height-bound
        h = height
        w = int(round(h * aspect))
    else:  # too tall (or exact) → width-bound
        w = width
        h = int(round(w / aspect))
    return w, h
