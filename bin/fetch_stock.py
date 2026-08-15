#!/usr/bin/env python3
"""Pull stock candidates (Unsplash + Pexels) for one product's landmarks.

Source ④ in `docs/DESIGN.md` 3.5, reached over HTTP through the live
`webuy-itinerary-mcp` service rather than with local API keys —
`lib/mcp_photos.py` explains why the keys live server side. The five
products done on 2026-08-14 had their `candidates.json` produced ad hoc;
this is the same job as `bin/fetch_commons.py` does for ③, written down so
a batch of nine does not depend on remembering the call shape.

**Why this level matters even though ③ covers more subjects.** Commons is
an archive: `lib/image_appeal.py` records that promoting it to the main
source is exactly what cost us the beauty axis (five products at
0.235–0.319 saturation against a house 0.421). Unsplash/Pexels are
organised by "does this look good", which is the axis Commons cannot
serve. Neither is sufficient alone — ③ knows the place, ④ knows the light.

**Region words go the opposite way from ③.** `fetch_commons.queries_for()`
strips qualifiers because Commons full text is close to AND. Stock search
ranks loosely instead, so the region string only helps it — the same split
`photo_source.search()` already makes (region-qualified for the stock
sources, bare for Commons).

The failure mode this level brings with it is `docs/DESIGN.md` 6.7: the
subject comes back right and the *place* comes back wrong. The first probe
run for WBLJG9 returned Ganden Sumtsenling Monastery in Shangri-La for
`Lijiang Old Town`. Stock carries no coordinates, so there is no GPS gate
here the way there is in `fetch_commons` — **nothing below rejects a
candidate for being somewhere else, and only a person looking at the
picture can.** Nothing here picks a photo.

    python3 bin/fetch_stock.py WBLJG9
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import mcp_photos

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_commons import block_name          # same block keys as ③
from make_payload import trip_type            # same "first three words" rule

WORK = Path("work")

# Region words handed to the stock search. Unlike ③ these *help* — see the
# module docstring. Keep them to province + country: naming the county
# narrows a loosely-ranked index for no gain.
STOCK_REGION = {
    "WBLJG9": "Yunnan China",
    "WBYNG": "Yunnan China",
    "WBYNB": "Yunnan China",
    # 这条线一半在福建(泉州/漳州/厦门)、一半在广东潮汕(潮州/揭阳/汕头)。
    # 写成单省会把另一半带偏——「潮州古城 Fujian China」排出来的是福建的东西。
    # stock 是松散排序不是 AND,多写一个省名不会把结果打空。
    "WBXMNM": "Fujian Guangdong China",
    "WBPCSX": "Hunan China",
    "WBWUX6": "Jiangsu China",
    "WBMZ7": "Guangdong China",
    "WBTFU8": "Sichuan China",
    "WB9XMN": "Guangdong China",
    "WBLCKG": "Chongqing China",
    "WBCKG6": "Chongqing China",
}


def fetch(code: str, per_subject: int = 6) -> dict:
    itinerary = json.loads((WORK / code / "itinerary.json").read_text("utf-8"))
    region = STOCK_REGION.get(code, "China")
    dest_dir = WORK / code / "cand"
    out: dict[str, dict] = {}
    session = mcp_photos._session()

    for section in itinerary["sections"]:
        day = section["day"]
        for item in section.get("trip_items", []):
            title = item["title"]["en"]
            if trip_type(title) in ("Transportation", "Accommodation"):
                continue
            subject = item.get("photo_subject") or title
            key = block_name(day, subject)
            if key in out:
                continue

            try:
                hits = mcp_photos.search(subject, region=region,
                                         count=per_subject, session=session)
            except mcp_photos.McpError as exc:
                # Loud, not silent: a sourcing gap must never be mistaken for
                # "no photo of this exists" (docs/DESIGN.md 6.9).
                print(f"  !! {key}: {exc}")
                out[key] = {"subject": subject, "region": region,
                            "day": day, "error": str(exc)[:200], "candidates": []}
                continue

            rows = []
            for cand in hits:
                path = dest_dir / f"{key}_{cand.n}.jpg"
                try:
                    if not path.exists():
                        mcp_photos.fetch(cand, path)
                except Exception as exc:                      # noqa: BLE001
                    print(f"  !! {key} #{cand.n} download: {exc}")
                    continue
                rows.append({"n": cand.n, "source": cand.source,
                             "title": cand.title, "url": cand.url,
                             "path": str(path)})

            out[key] = {"subject": subject, "region": region, "day": day,
                        "candidates": rows}
            flag = "   ← 0" if not rows else ""
            srcs = "/".join(sorted({r["source"] for r in rows})) or "-"
            print(f"  {key:<44} {len(rows)} 张 [{srcs}]{flag}")

    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    for code in argv[1:]:
        print(f"== {code}  (region={STOCK_REGION.get(code, 'China')!r})")
        blocks = fetch(code)
        path = WORK / code / "candidates.json"
        path.write_text(json.dumps(blocks, indent=2, ensure_ascii=False))
        total = sum(len(b["candidates"]) for b in blocks.values())
        filled = sum(1 for b in blocks.values() if b["candidates"])
        print(f"{code}: {total} 张候选,覆盖 {filled}/{len(blocks)} 个主体 → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
