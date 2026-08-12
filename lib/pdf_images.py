"""Pull the usable photos out of a Webuy brochure PDF.

Source #1 of the two-source image plan: whatever the brochure already
carries. These are the photos the product team chose, so they beat any
stock lookup on intent — but they are small (700–1075px across the three
launch samples) and the deck templates leave a lot of furniture behind
(logos, header bands, bullet glyphs), so everything is gated before use.

**Captions are a hint, never a fact.** `caption_hint` is the text sitting
directly under (or over) the image box. In WBCURC page 6 that text reads
"Tongren Grand Canyon 铜仁大峡谷" — a Guizhou landmark — while the photo is
the Flaming Mountains in Turpan, 3,000km away. The Xinjiang deck was built
from the Guizhou deck and the caption came along for the ride. So the
subject of a PDF photo is decided by *looking at it* (the agent is
multimodal; see skills/skybear-upload-images/SKILL.md), and the caption is
only ever offered as a prior.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from PIL import Image

from .image_spec import (
    CAROUSEL,
    MAX_ASPECT,
    MIN_ANY_EDGE,
    MIN_ASPECT,
    MIN_PDF_CROP_WIDTH,
    SECTION,
    SlotSpec,
    crop_window,
)


@dataclass
class PdfImage:
    """One raster extracted from the brochure, with everything needed to
    judge it — but no claim about what it depicts."""

    path: Path
    page: int  # 1-based
    index: int  # order within the page
    width: int
    height: int
    sha1: str
    kind: str = "photo"  # photo | route_map | cover_poster | furniture
    caption_hint: str = ""  # UNTRUSTED — see module docstring
    rejected: str = ""  # empty = kept; otherwise the gate that dropped it
    subject: str = ""  # filled in later by the multimodal pass
    day: int | None = None  # filled in later, once subject is known

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 0.0

    @property
    def long_edge(self) -> int:
        return max(self.width, self.height)

    def crop_width(self, slot: SlotSpec) -> int:
        """Width of the largest `slot`-ratio window inside this raster."""
        return crop_window(self.width, self.height, slot.aspect)[0]

    def fits(self, slot: SlotSpec) -> bool:
        """Can this photo fill `slot` without exceeding its upscale ceiling?"""
        return not self.rejected and self.crop_width(slot) >= slot.min_source_width

    @property
    def is_photo(self) -> bool:
        return not self.rejected and self.kind == "photo"

    @property
    def is_usable(self) -> bool:
        """A photograph, big enough for at least the smallest slot."""
        return self.is_photo and self.crop_width(SECTION) >= MIN_PDF_CROP_WIDTH

    @property
    def is_hero_grade(self) -> bool:
        """Sharp enough for the carousel, where it renders large."""
        return self.is_photo and self.fits(CAROUSEL)


@dataclass
class PdfImageSet:
    pdf: Path
    images: list[PdfImage] = field(default_factory=list)

    @property
    def usable(self) -> list[PdfImage]:
        return [i for i in self.images if i.is_usable]

    @property
    def hero_grade(self) -> list[PdfImage]:
        return [i for i in self.images if i.is_hero_grade]

    @property
    def undersized(self) -> list[PdfImage]:
        """Real photos that even a section tile would soften."""
        return [i for i in self.images if i.is_photo and not self.is_big_enough(i)]

    @property
    def route_maps(self) -> list[PdfImage]:
        """Candidates for wt_travel.route_map_url."""
        return [i for i in self.images if i.kind == "route_map" and not i.rejected]

    @property
    def rejected(self) -> list[PdfImage]:
        return [i for i in self.images if i.rejected]

    @staticmethod
    def is_big_enough(img: PdfImage) -> bool:
        return img.crop_width(SECTION) >= MIN_PDF_CROP_WIDTH


def _caption_near(page: fitz.Page, rect: fitz.Rect) -> str:
    """Text in the band just below the image, else just above it.

    Brochure captions sit tight under the photo ("Jiaxiu Pavilion 甲秀楼").
    The band is deliberately shallow so we don't hoover up body copy — and
    it still misfires often enough that callers must treat it as a guess.
    """
    for band in (
        fitz.Rect(rect.x0 - 24, rect.y1 - 4, rect.x1 + 24, rect.y1 + 34),
        fitz.Rect(rect.x0 - 24, rect.y0 - 34, rect.x1 + 24, rect.y0 + 4),
    ):
        text = " ".join(page.get_textbox(band).split())
        if text:
            return text[:120]
    return ""


def _render(doc: fitz.Document, xref: int) -> Image.Image | None:
    """Flatten an embedded raster to an RGB PIL image.

    Transparency is composited onto white rather than dropped: brochure
    PNGs use alpha for cut-out shapes, and discarding the channel leaves
    whatever garbage RGB sat under the transparent pixels.
    """
    try:
        pix = fitz.Pixmap(doc, xref)
    except Exception:
        return None
    if pix.colorspace is None:  # stencil mask, not a picture
        return None
    if pix.n - pix.alpha > 3:  # CMYK and friends
        pix = fitz.Pixmap(fitz.csRGB, pix)

    img = Image.open(io.BytesIO(pix.tobytes("png")))
    if img.mode in ("RGBA", "LA", "PA"):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.split()[-1])
        return flat
    return img.convert("RGB")


def _looks_like_route_map(img: Image.Image) -> bool:
    """Is this a schematic route map rather than a photograph?

    Every Webuy brochure carries one: a pale-blue province silhouette with
    city pins, dashed coach lines and flight arcs. It is a genuinely useful
    asset — it belongs in `wt_travel.route_map_url` — but dropping it into
    the carousel next to real scenery looks like a mistake.

    Thresholds are measured across the three launch brochures, where the
    three maps sit at saturation 0.09–0.12 against 0.25–0.73 for every
    photo, with far fewer distinct colour buckets. Saturation alone
    separates them; the flat-area terms guard against a genuinely muted
    photo (fog, snow) being misread as a diagram.
    """
    small = img.copy()
    small.thumbnail((220, 220))
    arr = np.asarray(small.convert("RGB"), dtype=np.int16)

    channel_max = arr.max(axis=2)
    channel_min = arr.min(axis=2)
    saturation = np.where(
        channel_max > 0, (channel_max - channel_min) / np.maximum(channel_max, 1), 0
    ).mean()
    if saturation >= 0.20:
        return False

    near_white = (arr > 235).all(axis=2).mean()
    buckets, counts = np.unique((arr // 32).reshape(-1, 3), axis=0, return_counts=True)
    flat_share = counts.max() / len(arr.reshape(-1, 3))
    busy_buckets = int((counts > len(arr.reshape(-1, 3)) * 0.005).sum())

    return (near_white > 0.20 or flat_share > 0.40) and busy_buckets <= 20


def _is_cover_poster(page: fitz.Page, rect: fitz.Rect) -> bool:
    """Is this the full-bleed cover artwork?

    Page 1 of every brochure is one exported graphic — tour title, feature
    icons, a photo collage and a promo badge, all rasterised. It reads as a
    photo to every colour statistic, so the tell is structural: the image
    fills the page and the page has **no text layer at all** (0 characters
    in all three samples), because the type is baked into the pixels.
    """
    if len(page.get_text().strip()) >= 50:
        return False
    page_area = page.rect.width * page.rect.height
    return page_area > 0 and (rect.width * rect.height) / page_area >= 0.80


def _gate(width: int, height: int) -> str:
    """Return the name of the gate this raster fails, or '' if it passes."""
    if min(width, height) < MIN_ANY_EDGE:
        return f"furniture: {width}x{height} below {MIN_ANY_EDGE}px min edge"
    aspect = width / height
    if aspect > MAX_ASPECT:
        return f"banner: aspect {aspect:.2f} > {MAX_ASPECT}"
    if aspect < MIN_ASPECT:
        return f"rule/strip: aspect {aspect:.2f} < {MIN_ASPECT:.2f}"
    return ""


def extract(pdf: str | Path, out_dir: str | Path) -> PdfImageSet:
    """Extract every raster from `pdf`, gate it, and write keepers to disk.

    Rejected rasters are recorded (with the reason) but not written — the
    reason list is what the planner reads when a day comes up short.
    """
    pdf = Path(pdf)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf)
    result = PdfImageSet(pdf=pdf)
    seen: dict[str, PdfImage] = {}

    for page_no, page in enumerate(doc, start=1):
        for idx, info in enumerate(page.get_images(full=True)):
            xref = info[0]
            picture = _render(doc, xref)
            if picture is None:
                continue
            width, height = picture.size
            buf = io.BytesIO()
            picture.save(buf, "PNG")
            data = buf.getvalue()
            sha1 = hashlib.sha1(data).hexdigest()

            # The same logo/banner is re-placed on every page; keep the
            # first sighting only so it can be rejected once.
            if sha1 in seen:
                continue

            reason = _gate(width, height)
            img = PdfImage(
                path=out_dir / f"p{page_no:02d}_{idx}_{width}x{height}.png",
                page=page_no,
                index=idx,
                width=width,
                height=height,
                sha1=sha1,
                rejected=reason,
            )
            if reason:
                img.kind = "furniture"
            else:
                img.path.write_bytes(data)
                rects = page.get_image_rects(xref)
                if rects:
                    img.caption_hint = _caption_near(page, rects[0])
                    if _is_cover_poster(page, rects[0]):
                        img.kind = "cover_poster"
                if img.kind == "photo" and _looks_like_route_map(picture):
                    img.kind = "route_map"
            seen[sha1] = img
            result.images.append(img)

    doc.close()
    return result
