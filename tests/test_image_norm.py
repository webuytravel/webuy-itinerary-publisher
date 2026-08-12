import numpy as np
import pytest
from PIL import Image

from lib.image_norm import normalise, smart_crop
from lib.image_spec import CAROUSEL, SECTION


def _noise(width: int, height: int, seed: int = 0) -> Image.Image:
    rng = np.random.default_rng(seed)
    return Image.fromarray(
        rng.integers(0, 255, (height, width, 3), dtype=np.uint8), "RGB")


def test_output_is_exactly_the_slot_size(tmp_path):
    src = tmp_path / "in.png"
    _noise(900, 1400).save(src)
    result = normalise(src, tmp_path / "out.jpg", CAROUSEL)
    assert (result.width, result.height) == (CAROUSEL.width, CAROUSEL.height)
    with Image.open(result.path) as out:
        assert out.size == (CAROUSEL.width, CAROUSEL.height)


def test_upscale_is_measured_against_the_crop_not_the_file(tmp_path):
    # 942x579 crops to 772 wide, so the honest factor is 1440/772 = 1.87,
    # not 1440/942 = 1.53. Reporting the flattering number would let soft
    # images through the review page unflagged.
    src = tmp_path / "in.png"
    _noise(942, 579).save(src)
    result = normalise(src, tmp_path / "out.jpg", CAROUSEL)
    assert result.upscale == pytest.approx(1440 / 772, abs=0.01)


def test_downscaling_reports_an_upscale_below_one(tmp_path):
    src = tmp_path / "in.png"
    _noise(3000, 2000).save(src)
    result = normalise(src, tmp_path / "out.jpg", SECTION)
    assert result.upscale < 1.0
    assert not result.is_soft


def test_smart_crop_follows_the_detail(tmp_path):
    # Flat sky on top, textured ground at the bottom: the 4:3 window should
    # slide down to the busy half rather than centring blindly.
    canvas = Image.new("RGB", (800, 1600), (140, 180, 230))
    canvas.paste(_noise(800, 700, seed=3), (0, 900))
    cropped, (_, top) = smart_crop(canvas, CAROUSEL.aspect)
    assert cropped.size == (800, 600)
    assert top > 500


def test_encoded_file_respects_the_byte_cap(tmp_path):
    src = tmp_path / "in.png"
    _noise(4000, 3000).save(src)  # noise is the worst case for JPEG
    result = normalise(src, tmp_path / "out.jpg", CAROUSEL)
    assert result.bytes <= CAROUSEL.max_bytes


def test_alpha_sources_do_not_come_out_black(tmp_path):
    src = tmp_path / "in.png"
    Image.new("RGBA", (1000, 800), (255, 0, 0, 0)).save(src)
    result = normalise(src, tmp_path / "out.jpg", SECTION)
    with Image.open(result.path) as out:
        assert out.mode == "RGB"
