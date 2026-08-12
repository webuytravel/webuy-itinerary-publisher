import numpy as np
from PIL import Image

from lib.image_spec import CAROUSEL, SECTION
from lib.pdf_images import PdfImage, _gate, _looks_like_route_map


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
