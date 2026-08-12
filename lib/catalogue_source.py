"""Source #1.5: photos Webuy already owns, from its own published tours.

Between the brochure and open stock sits a source that beats both for most
China tours — the images already on `webuytravel.sg`. A new Guizhou package
visits the same waterfalls as the Guizhou package already selling, and those
photos are:

* **already licensed** — no Shutterstock invoice, no CC attribution to track;
* **already the house style** — same photographers, same grade, so a gallery
  built from them is consistent with the rest of the catalogue by
  construction, which open stock never is;
* **already the right size** — 1080-class on the long edge, straight off the
  OSS bucket the uploader writes back to;
* **already labelled** — each `<img>` carries the trip-item name in `alt`
  ("Maling River Canyon", "Urho Ghost City (Devil's Town)"), which comes out
  of the Skybear CMS rather than from a designer's caption layer, so unlike
  the brochure captions it is reliable.

Coverage is the catch. It works when a sibling product visits the same
places: Guizhou (`tours/115`) and Chongqing (`tours/108`) between them cover
almost every WBCKWE landmark, and Altay (`tours/112`) covers most of WBCURC's
Xinjiang. It fails when nothing similar is published — no live tour covers
Shanxi, and the Inner Mongolia product carries one image, so WBCHET gets
nothing from here.

The listing pages sit behind Cloudflare, so the harvest step runs in the
agent's browser (see `HARVEST_JS`) rather than over plain HTTP. The image
bucket itself is open, which is why `fetch` here needs no browser.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .photo_source import USER_AGENT, download

OSS_BASE = "https://prod-webuysg.oss.webuy.ren/travel-video"

CHINA_INDEX = "https://webuytravel.sg/china-tours"

# Run this in the agent's browser on a /tours/<id>-<slug> page. It scrolls to
# force the lazy images to resolve, then returns [[image_id, alt], ...].
HARVEST_JS = """
(async()=>{await new Promise(r=>setTimeout(r,2200));
window.scrollTo(0,document.body.scrollHeight); await new Promise(r=>setTimeout(r,2600));
window.scrollTo(0,0); await new Promise(r=>setTimeout(r,900));
const out=[];
document.querySelectorAll('img').forEach(i=>{
  const src=(i.currentSrc||i.src||i.getAttribute('data-src')||'');
  if(!src.includes('travel-video')) return;
  out.push([src.split('?')[0].split('/').pop().replace('.jpg',''),(i.alt||'').slice(0,60)]);
});
return JSON.stringify([...new Map(out.map(o=>[o[0],o])).values()])})()
"""


@dataclass
class CatalogueImage:
    image_id: str
    alt: str
    tour: str  # the /tours/... slug it came from
    width: int = 0
    height: int = 0
    bytes: int = 0

    @property
    def url(self) -> str:
        return f"{OSS_BASE}/{self.image_id}.jpg"


def _slugish(text: str) -> str:
    """Lowercase, with every run of non-alphanumerics collapsed to a space.

    Lets a URL slug ("10d8n-desert-and-grassland") be compared against the
    alt text it was generated from ("10D8N Desert And Grassland …"), which
    differ only in their separators.
    """
    return " ".join(
        "".join(c if c.isalnum() else " " for c in text.lower()).split())


def parse_harvest(raw: str | list, tour: str) -> list[CatalogueImage]:
    """Turn `HARVEST_JS` output into records, dropping the hero.

    The first image on a product page is the product's own hero and its alt
    is the tour title, not a landmark — useless for matching a day.
    """
    rows = json.loads(raw) if isinstance(raw, str) else raw
    # "tours/75-10d8n-desert-and-grassland" → "10d8n desert and grassland"
    slug = _slugish(tour.split("/")[-1].split("-", 1)[-1])
    out = []
    for image_id, alt in rows:
        alt = (alt or "").strip()
        if not alt:
            continue
        # The alt is often the title truncated, so compare on the shorter.
        normalised = _slugish(alt)
        head = min(len(normalised), len(slug), 24)
        if head and normalised[:head] == slug[:head]:
            continue
        out.append(CatalogueImage(image_id=image_id, alt=alt, tour=tour))
    return out


def probe(image: CatalogueImage) -> CatalogueImage:
    """Fill in real dimensions via the OSS `image/info` endpoint.

    Cheaper than downloading to measure, and it is how we confirm a
    catalogue image clears a slot floor before committing to it.
    """
    try:
        req = Request(f"{image.url}?x-oss-process=image/info",
                      headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=20) as response:
            info = json.loads(response.read())
        image.width = int(info.get("width") or 0)
        image.height = int(info.get("height") or 0)
        image.bytes = int(info.get("size") or 0)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        pass
    return image


def fetch(image: CatalogueImage, dest: str | Path) -> Path:
    """Download the full-size original (no `x-oss-process` resize chain)."""
    dest = Path(dest)
    download(image.url, dest)
    return dest


def match(images: list[CatalogueImage], terms: list[str]) -> list[CatalogueImage]:
    """Catalogue images whose alt mentions any of `terms`.

    Substring matching on purpose: the CMS alt text carries trailing
    inclusions — "Wanfenglin (Ten Thousand Peaks Forest) (includes eco…" —
    so an exact-name match would miss almost everything.
    """
    lowered = [t.lower() for t in terms]
    return [i for i in images
            if any(term in i.alt.lower() for term in lowered)]
