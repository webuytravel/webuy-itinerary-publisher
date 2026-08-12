"""Source #2: find a photo on the web when the brochure can't supply one.

This mirrors the selection rules already in production in the sibling repo
`webuy-itinerary-creation` (`scripts/fetch_landscape_photos.py`), which
builds the printed PDF itineraries. Same rules, same order, so a tour's
brochure and its Skybear listing draw from the same pool and look like one
product. The two repos are independent (see the workspace CLAUDE.md), so the
logic is ported rather than imported — keep them in step by hand.

The rules being mirrored:

* **Source priority** — Shutterstock (Webuy's licensed library) → Unsplash →
  Pexels → Wikimedia Commons. Paid-and-curated first because it wins on
  quality for niche Chinese landmarks; Commons last because it is
  documentary rather than beautiful, but it is keyless and never empty.
* **GPS gate** — Commons results carry coordinates. Anything more than
  `max_distance_km` from the expected location is dropped outright. This is
  the check that stops a Xinjiang photo landing in a Guizhou tour.
* **Two-axis choice** — accuracy first (is this really the named place?),
  then beauty (would it sell?). Never beauty alone.

**Where this port deliberately differs.** The sibling script runs both axes
through Gemini (`_verify_match` + `_aesthetic_score`), which needs
GEMINI_API_KEY and costs ~30–60s per photo. Here the function returns
*ranked candidates* and the calling agent — which is multimodal — looks at
them and picks. That is the same trade the sibling repo's own MCP tool
recommends (`fetch_photo(quick=True)`: "you are multimodal, so look at them
and pick the best yourself"), and it removes a key dependency from a plugin
that Planners install themselves. `SKILL.md` carries the judging criteria
that the Gemini prompts used to hold.
"""

from __future__ import annotations

import json
import math
import os
import ssl
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
UNSPLASH_API = "https://api.unsplash.com/search/photos"
PEXELS_API = "https://api.pexels.com/v1/search"
SHUTTERSTOCK_API = "https://api.shutterstock.com/v2/images/search"

USER_AGENT = "webuy-skybear-uploader/0.3 (+https://github.com/ctwang54-create/skybear-uploader)"

# Same default as the sibling repo: a photo tagged more than this far from
# the expected place is a different place.
DEFAULT_MAX_DISTANCE_KM = 250.0


@dataclass
class Candidate:
    url: str
    source: str
    title: str
    width: int
    height: int
    license: str = ""
    credit: str = ""
    lat: float | None = None
    lon: float | None = None

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 0.0


def _ctx() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL = _ctx()


def _get_json(url: str, headers: dict | None = None, timeout: int = 30) -> dict:
    req = Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urlopen(req, timeout=timeout, context=_SSL) as response:
        return json.loads(response.read())


def download(url: str, dest: str | Path, timeout: int = 60) -> int:
    """Fetch `url` to `dest`, returning the byte count."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout, context=_SSL) as response, dest.open("wb") as out:
        total = 0
        while chunk := response.read(65536):
            out.write(chunk)
            total += len(chunk)
    return total


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


# --- per-source search ------------------------------------------------

def _commons(query: str, n: int) -> list[Candidate]:
    """Wikimedia Commons. Keyless, and the only source carrying GPS."""
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": "6",
        "gsrlimit": str(n), "prop": "imageinfo",
        "iiprop": "url|size|extmetadata|commonmetadata",
        "iiurlwidth": "2000",
    }
    try:
        data = _get_json(f"{COMMONS_API}?{urlencode(params)}")
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return []

    out = []
    for page in (data.get("query", {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        if not info.get("thumburl") and not info.get("url"):
            continue
        meta = info.get("extmetadata") or {}
        lat = lon = None
        for entry in info.get("commonmetadata") or []:
            if entry.get("name") == "GPSLatitude":
                lat = _as_float(entry.get("value"))
            elif entry.get("name") == "GPSLongitude":
                lon = _as_float(entry.get("value"))
        out.append(Candidate(
            url=info.get("thumburl") or info["url"],
            source="commons",
            title=page.get("title", "").replace("File:", ""),
            width=int(info.get("thumbwidth") or info.get("width") or 0),
            height=int(info.get("thumbheight") or info.get("height") or 0),
            license=(meta.get("LicenseShortName") or {}).get("value", ""),
            credit=_strip_tags((meta.get("Artist") or {}).get("value", "")),
            lat=lat, lon=lon,
        ))
    return out


def _unsplash(query: str, n: int) -> list[Candidate]:
    key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not key:
        return []
    url = f"{UNSPLASH_API}?{urlencode({'query': query, 'per_page': n, 'orientation': 'landscape'})}"
    try:
        data = _get_json(url, {"Authorization": f"Client-ID {key}"})
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return []
    return [
        Candidate(
            url=hit["urls"]["raw"] + "&w=2000&fm=jpg&q=85",
            source="unsplash",
            title=(hit.get("description") or hit.get("alt_description") or "")[:120],
            width=int(hit.get("width") or 0),
            height=int(hit.get("height") or 0),
            license="Unsplash License",
            credit=(hit.get("user") or {}).get("name", ""),
        )
        for hit in data.get("results", [])
    ]


def _pexels(query: str, n: int) -> list[Candidate]:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    url = f"{PEXELS_API}?{urlencode({'query': query, 'per_page': n, 'orientation': 'landscape'})}"
    try:
        data = _get_json(url, {"Authorization": key})
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return []
    return [
        Candidate(
            url=(hit.get("src") or {}).get("large2x") or (hit.get("src") or {}).get("original", ""),
            source="pexels",
            title=(hit.get("alt") or "")[:120],
            width=int(hit.get("width") or 0),
            height=int(hit.get("height") or 0),
            license="Pexels License",
            credit=hit.get("photographer", ""),
        )
        for hit in data.get("photos", [])
    ]


def _shutterstock(query: str, n: int) -> list[Candidate]:
    """Webuy's licensed library — best quality for niche Chinese landmarks.

    Returns watermarked preview URLs. Anything chosen from here must be
    licensed through the Webuy Shutterstock account before it ships; the
    same caveat the sibling repo carries.
    """
    token = os.environ.get("SHUTTERSTOCK_TOKEN")
    if not token:
        return []
    params = {"query": query, "per_page": n, "orientation": "horizontal",
              "image_type": "photo", "sort": "popular"}
    try:
        data = _get_json(f"{SHUTTERSTOCK_API}?{urlencode(params)}",
                         {"Authorization": f"Bearer {token}"})
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return []
    out = []
    for hit in data.get("data", []):
        preview = (hit.get("assets") or {}).get("huge_thumb") or {}
        if not preview.get("url"):
            continue
        out.append(Candidate(
            url=preview["url"], source="shutterstock",
            title=(hit.get("description") or "")[:120],
            width=int(preview.get("width") or 0),
            height=int(preview.get("height") or 0),
            license="Shutterstock (licence before use)",
            credit=hit.get("contributor", {}).get("id", ""),
        ))
    return out


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _strip_tags(html: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", html or "").strip()[:80]


# --- top level --------------------------------------------------------

def search(
    subject: str,
    region: str = "",
    n_per_source: int = 6,
    min_width: int = 720,
    expected_loc: tuple[float, float] | None = None,
    max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
) -> list[Candidate]:
    """Ranked photo candidates for one subject, best source first.

    Returns candidates for the caller to judge — it does NOT pick a winner.
    Filtering here is only the mechanical part: too small, or provably in
    the wrong place. Accuracy and beauty are the agent's call.
    """
    with_region = f"{subject} {region}".strip()
    candidates: list[Candidate] = []

    # Stock sites rank loosely, so the extra region words only help them.
    for fetch in (_shutterstock, _unsplash, _pexels):
        candidates += fetch(with_region, n_per_source)

    # Commons full-text is close to AND — every extra word has to appear in
    # the file page or the result vanishes. Measured: "Hongyadong" returns 6
    # hits, "Chongqing Hongyadong night Guizhou China" returns 0. So query
    # the bare subject first and only fall back to the region-qualified form
    # when the subject alone is too thin or ambiguous.
    commons_hits = _commons(subject, n_per_source)
    if len(commons_hits) < n_per_source and region:
        commons_hits += _commons(with_region, n_per_source)
    candidates += commons_hits

    kept: list[Candidate] = []
    seen_urls: set[str] = set()
    for candidate in candidates:
        if not candidate.url or candidate.url in seen_urls:
            continue
        # A source that under-reports its size (Commons thumbs) still gets a
        # chance — only reject when we know it is too small.
        if candidate.width and candidate.width < min_width:
            continue
        if expected_loc and candidate.lat is not None and candidate.lon is not None:
            if haversine_km(expected_loc, (candidate.lat, candidate.lon)) > max_distance_km:
                continue
        seen_urls.add(candidate.url)
        kept.append(candidate)
    return kept


def available_sources() -> dict[str, bool]:
    """Which sources this environment can actually reach.

    Commons is always true; the rest depend on keys the Planner never has
    to hold — a keyless run still works, just with a smaller pool.
    """
    return {
        "shutterstock": bool(os.environ.get("SHUTTERSTOCK_TOKEN")),
        "unsplash": bool(os.environ.get("UNSPLASH_ACCESS_KEY")),
        "pexels": bool(os.environ.get("PEXELS_API_KEY")),
        "commons": True,
    }
