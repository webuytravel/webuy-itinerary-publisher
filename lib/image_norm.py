"""Bring any source photo onto the house standard for one Skybear slot.

Two jobs, in order:

1. **Crop to the slot ratio** — and crop *well*. A centre crop is fine for a
   photo that is already close to 4:3, but the brochures are full of 3:4
   portraits (a 1080×1440 waterfall, a 737×1038 lake) where a centre crop
   slices the subject in half. So the crop window is chosen by detail
   density instead of by geometry.

2. **Resize and encode** — Lanczos to the slot's exact pixel size, JPEG at
   the slot quality, stepping quality down if the file lands over the cap.

Everything ends up at one ratio per slot, which is the point: the live
catalogue mixes 3:4, 4:3 and 9:16 in a single carousel and it reads as
inconsistent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from .image_spec import SlotSpec, crop_window


@dataclass(frozen=True)
class Normalised:
    path: Path
    width: int
    height: int
    bytes: int
    upscale: float  # >1 means the source was smaller than the slot
    crop_offset: tuple[int, int]

    @property
    def is_soft(self) -> bool:
        """Upscaled far enough that a viewer could notice at full size."""
        return self.upscale > 1.35


def _energy_profile(img: Image.Image, axis: int) -> np.ndarray:
    """Detail density along one axis, as a 1-D array.

    Edge magnitude is a decent stand-in for "where the subject is": sky,
    water and blurred backgrounds are flat, while architecture, faces,
    horizons and foliage are not. Computed on a downscaled copy — we only
    need the shape of the curve, not its precision.
    """
    small = img.convert("L")
    small.thumbnail((256, 256), Image.BILINEAR)
    edges = np.asarray(small.filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    return edges.sum(axis=axis)


def _best_offset(profile: np.ndarray, window_frac: float, full: int) -> int:
    """Slide a window across `profile` and return the highest-energy start.

    `profile` is at thumbnail scale; `full` is the real pixel extent, so the
    result is scaled back up before use.
    """
    n = len(profile)
    win = max(1, int(round(n * window_frac)))
    if win >= n:
        return 0
    # Prefix sums make the slide O(n) instead of O(n·win).
    cumulative = np.concatenate([[0.0], np.cumsum(profile)])
    sums = cumulative[win:] - cumulative[:-win]
    # Nudge toward the centre so two near-equal windows don't produce a
    # jarring edge-hugging crop.
    centre = (len(sums) - 1) / 2 if len(sums) > 1 else 0
    positions = np.arange(len(sums))
    bias = 1.0 - 0.15 * np.abs(positions - centre) / max(centre, 1)
    start = int(np.argmax(sums * bias))
    return int(round(start / n * full))


def smart_crop(img: Image.Image, aspect: float) -> tuple[Image.Image, tuple[int, int]]:
    """Crop `img` to `aspect`, keeping the densest region."""
    width, height = img.size
    target_w, target_h = crop_window(width, height, aspect)
    if (target_w, target_h) == (width, height):
        return img, (0, 0)

    if target_w < width:  # crop horizontally
        left = _best_offset(_energy_profile(img, axis=0), target_w / width, width)
        left = min(left, width - target_w)
        box = (left, 0, left + target_w, height)
    else:  # crop vertically
        top = _best_offset(_energy_profile(img, axis=1), target_h / height, height)
        top = min(top, height - target_h)
        box = (0, top, width, top + target_h)

    return img.crop(box), (box[0], box[1])


def normalise(src: str | Path, dest: str | Path, slot: SlotSpec) -> Normalised:
    """Crop, resize and encode `src` into `dest` at `slot`'s standard."""
    src, dest = Path(src), Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(src) as raw:
        # EXIF orientation first — otherwise a phone-shot landscape crops
        # as though it were a portrait.
        img = ImageOps.exif_transpose(raw)
        if img.mode != "RGB":
            img = img.convert("RGB")

        cropped, offset = smart_crop(img, slot.aspect)
        upscale = slot.width / cropped.width
        resized = cropped.resize((slot.width, slot.height), Image.LANCZOS)

        quality = slot.jpeg_quality
        while True:
            resized.save(dest, "JPEG", quality=quality, optimize=True,
                         progressive=True, subsampling=1)
            size = dest.stat().st_size
            if size <= slot.max_bytes or quality <= 60:
                break
            quality -= 6

    return Normalised(
        path=dest,
        width=slot.width,
        height=slot.height,
        bytes=size,
        upscale=round(upscale, 3),
        crop_offset=offset,
    )
