"""The BEAUTY axis — does a photo look like something we'd put in front of a customer.

This project had only an ACCURACY axis. Every gate before this one asked "is
this really that place?" — GPS, subject matching, a human looking at contact
sheets — and none of them asked "does it look good?". The sibling repo that
builds the printed brochures (`webuy-itinerary-creation`,
`scripts/fetch_landscape_photos.py`) has had both axes from the start:

    ACCURACY — `_verify_match` gates wrong-subject photos.
    BEAUTY   — `_aesthetic_score` rates 0-10 as a travel-magazine photo
               editor, and its prompt is explicit about what loses points:
               "Score LOW for dull, grey, cluttered, flat, or snapshot-like
                images; score HIGH for striking, vivid, well-composed,
                postcard-worthy shots."

That repo also orders its sources by beauty for the marketing path —
Shutterstock, then Unsplash/Pexels, and **Wikimedia Commons explicitly last,
labelled "documentary last resort"**. This project did the opposite: Commons
was promoted to the main source precisely because it is documentary (it
carries GPS, so the place can be proven). We bought accuracy with the axis
the other repo optimises, and the result was measurably duller pictures.

**Measured 2026-08-14** — mean saturation, against the 48 catalogue images
that are the house standard because they are literally what ships on
`webuytravel.sg`:

    house standard          0.421
    WBCKWE trip photos      0.235   ← 56% of house
    WBINC9                  0.272
    WBSZX1                  0.303
    WBCHET                  0.312
    WBCURC                  0.319

Brightness was fine (0.44–0.51 against a house 0.482). **The complaint was
never darkness, it was greyness** — and the numbers say the same thing.

The gate here is deliberately local and cheap rather than a second Gemini
call: it runs on every candidate for free, and the multimodal look that
follows is what catches the things arithmetic cannot see. Thresholds are the
house 10th percentile, so "as bad as the worst tenth of what we already
ship" is the floor, not an invented number.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

# 10th percentile of the 48 live catalogue images. Anything below this is
# duller/darker/flatter than 90% of what the company already sells with.
MIN_SATURATION = 0.181
MIN_LUMINANCE = 0.360
MIN_CONTRAST = 0.142

# Above this the photo is blown out or fogged rather than bright.
MAX_LUMINANCE = 0.80


@dataclass(frozen=True)
class Appeal:
    """Measured colour appeal of one image."""

    luminance: float   # 0-1, Rec.709 luma, mean
    saturation: float  # 0-1, HSV-style S, mean
    contrast: float    # 0-1, std-dev of luma

    @property
    def is_dull(self) -> bool:
        """Below the house floor on any axis — do not ship without a reason."""
        return (self.saturation < MIN_SATURATION
                or self.luminance < MIN_LUMINANCE
                or self.contrast < MIN_CONTRAST
                or self.luminance > MAX_LUMINANCE)

    @property
    def why(self) -> str:
        bad = []
        if self.saturation < MIN_SATURATION:
            bad.append(f"灰(饱和 {self.saturation:.3f} < {MIN_SATURATION})")
        if self.luminance < MIN_LUMINANCE:
            bad.append(f"暗(亮度 {self.luminance:.3f} < {MIN_LUMINANCE})")
        if self.luminance > MAX_LUMINANCE:
            bad.append(f"过曝(亮度 {self.luminance:.3f} > {MAX_LUMINANCE})")
        if self.contrast < MIN_CONTRAST:
            bad.append(f"平(对比 {self.contrast:.3f} < {MIN_CONTRAST})")
        return " / ".join(bad)

    @property
    def score(self) -> float:
        """Rank-ordering number, house median = 1.0.

        Saturation is weighted hardest because it is the axis the five
        products actually failed on, and the one a reader reads as "grey".
        """
        return (self.saturation / 0.412) * 0.6 + (self.luminance / 0.490) * 0.2 \
            + (self.contrast / 0.215) * 0.2


def measure(path: str | Path, box: int = 320) -> Appeal | None:
    """Appeal of one image, or None if it cannot be read.

    Downsamples first: these are whole-image averages, so full resolution
    buys nothing and costs a lot across a few hundred candidates.
    """
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((box, box))
            arr = np.asarray(im).astype(np.float32) / 255.0
    except Exception:                                     # noqa: BLE001
        return None
    high = arr.max(axis=2)
    low = arr.min(axis=2)
    luma = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
    sat = np.where(high > 0, (high - low) / np.maximum(high, 1e-6), 0.0)
    return Appeal(luminance=float(luma.mean()),
                  saturation=float(sat.mean()),
                  contrast=float(luma.std()))
