import io

import fitz
import numpy as np
from PIL import Image

from lib.image_spec import CAROUSEL, SECTION
from lib.pdf_images import (
    PdfImage,
    _gate,
    _looks_like_route_map,
    _looks_like_text_page,
    extract,
)


def _img(width: int, height: int, **kw) -> PdfImage:
    return PdfImage(path=None, page=1, index=0, width=width, height=height,
                    sha1="x", **kw)


def test_gate_drops_icons():
    # The brochures embed 87x81 and 67x64 bullet glyphs and 160x160 badges.
    assert "furniture" in _gate(87, 81)
    assert "furniture" in _gate(160, 160)


def test_gate_drops_header_bands():
    # 1562x386 and 1294x320 decorative headers, seen in all three decks.
    assert "banner" in _gate(1562, 386)
    assert "banner" in _gate(1294, 320)


def test_gate_keeps_real_photos():
    for size in ((733, 704), (942, 579), (1024, 1166), (860, 1146)):
        assert _gate(*size) == ""


def test_grading_uses_the_crop_width():
    # 942x579 has a 942px long edge but only a 772px 4:3 crop — big enough
    # for the carousel (720 floor), and it must not be judged on 942.
    photo = _img(942, 579)
    assert photo.crop_width(CAROUSEL) == 772
    assert photo.is_hero_grade

    # 744x385 looks similar but crops to 513 — below even the section floor.
    small = _img(744, 385)
    assert not small.is_usable
    assert not small.is_hero_grade


def test_section_only_photos_are_usable_but_not_hero_grade():
    photo = _img(719, 499)  # crops to 665
    assert photo.crop_width(SECTION) == 665
    assert photo.is_usable
    assert not photo.is_hero_grade


def test_non_photo_kinds_never_reach_a_slot():
    # The page-1 cover artwork is 1024x1166 — large enough to pass every
    # geometric gate, which is why it needs its own kind.
    poster = _img(1024, 1166, kind="cover_poster")
    assert not poster.is_usable
    assert not poster.is_hero_grade

    route = _img(897, 718, kind="route_map")
    assert not route.is_hero_grade


def test_route_map_classifier_separates_diagrams_from_photos():
    # A schematic: pale flat fill on white, few distinct colours.
    diagram = Image.new("RGB", (900, 700), (255, 255, 255))
    diagram.paste(Image.new("RGB", (520, 420), (214, 226, 245)), (190, 140))
    assert _looks_like_route_map(diagram)

    rng = np.random.default_rng(11)
    photo = Image.fromarray(
        rng.integers(0, 255, (700, 900, 3), dtype=np.uint8), "RGB")
    assert not _looks_like_route_map(photo)


def _text_slab(height: int = 854, width: int = 978, pitch: int = 26) -> Image.Image:
    """A rasterised page of body copy, to the numbers that decide it.

    Modelled on ACKMG12T page 7: 4px word bars of dark blue on a flat pale
    blue ground, one line every 26px. Reproducing the statistics matters,
    not the glyphs — the fixture lands at ink share 0.11, saturation 0.13
    and flat share 0.58 against 0.10 / 0.09 / 0.55 for the real raster.
    """
    page = np.full((height, width, 3), (219, 230, 238), dtype=np.uint8)
    rng = np.random.default_rng(3)
    for top in range(40, height - 30, pitch):
        x = 55
        while x < width - 60:
            word = int(rng.integers(28, 95))
            page[top:top + 4, x:min(x + word, width - 55)] = (24, 62, 104)
            x += word + 12
    return Image.fromarray(page)


def test_a_rasterised_text_page_is_not_mistaken_for_a_route_map():
    # ACKMG12T ships its "Special Terms and Conditions" pages as single
    # rasters with no picture on them. Colour statistics read them as
    # diagrams, so page 7 was classified route_map — and compose.py takes
    # the first route_map for wt_travel.routeMapUrl, so a page of
    # cancellation terms would have shipped as the product's route map.
    slab = _text_slab()
    assert _looks_like_text_page(slab)
    assert _looks_like_route_map(slab)  # why the colour terms can't decide it

    # The schematic it sits next to has no baseline pitch to find, so the
    # new gate must leave the genuine route map alone.
    diagram = Image.new("RGB", (900, 700), (255, 255, 255))
    diagram.paste(Image.new("RGB", (520, 420), (214, 226, 245)), (190, 140))
    assert not _looks_like_text_page(diagram)
    assert _looks_like_route_map(diagram)


def test_a_text_page_is_gated_out_before_either_classifier_votes(tmp_path):
    # The gate runs inside `extract`, so the slab reaches no slot at all —
    # not the route-map slot, and not the carousel either. 978x854 clears
    # every geometric gate and crops to a hero-grade 4:3 window, so a fix
    # that only taught the route-map classifier would move the terms page
    # from one wrong slot to another.
    slab = _text_slab()
    assert _gate(*slab.size) == ""

    buf = io.BytesIO()
    slab.save(buf, "PNG")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(40, 120, 550, 565), stream=buf.getvalue())
    pdf = tmp_path / "terms.pdf"
    doc.save(pdf)
    doc.close()

    found = extract(pdf, tmp_path / "raw")
    assert found.route_maps == []
    assert found.usable == []
    assert [i.rejected for i in found.rejected] == ["text page: 978x854 slab of body copy"]


def test_a_muted_photo_is_not_mistaken_for_a_diagram():
    # Fog and snow push saturation down, so the flat-area terms are what
    # have to carry the distinction. A photograph keeps low-frequency
    # structure — a tonal gradient, soft shapes — that survives the
    # classifier's downscale, whereas a diagram stays flat.
    height, width = 700, 900
    rng = np.random.default_rng(5)
    gradient = np.linspace(70, 235, height, dtype=np.float32)[:, None]
    base = np.repeat(gradient, width, axis=1)
    base = base + rng.normal(0, 14, (height, width))
    columns = np.linspace(-40, 40, width, dtype=np.float32)[None, :]
    base = np.clip(base + columns, 0, 255)
    stacked = np.stack([base, base * 0.94, base * 1.04], axis=2)
    muted = np.clip(stacked, 0, 255).astype(np.uint8)
    assert not _looks_like_route_map(Image.fromarray(muted, "RGB"))
