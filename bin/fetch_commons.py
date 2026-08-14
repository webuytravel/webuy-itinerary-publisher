#!/usr/bin/env python3
"""Pull Wikimedia Commons candidates for one product's landmarks.

Source ② in `docs/DESIGN.md` 3.35. Commons was written off on 2026-08-06 as
"an archive, not a photo library" and switched off; re-measuring on 08-13
showed the opposite for exactly the subjects Pexels/Unsplash cannot do —
named Chinese heritage sites. 西夏陵 came back as 5 real photos of the
rammed-earth mausolea (Pexels returned three Terracotta Army shots and a
Big Wild Goose Pagoda); 乌兰哈达火山 and 开平碉楼 likewise.

Two rules the query construction has to respect, both measured:

* **Search the bare English name, never the region-qualified string.**
  Commons full-text is close to AND — every extra word removes results.
  `Hongyadong` returns 6 hits, `Chongqing Hongyadong night Guizhou China`
  returns 0. This is what made the 08-06 probe look empty.
* **Keep `license` and `credit`.** Commons is the only source that hands
  back the author and the licence, and roughly nine in ten files are
  CC BY / CC BY-SA. Business signed off on using them (2026-08-14) without
  solving where attribution goes, so the data has to survive into
  `plan.json` — the day someone has to add credits, re-deriving them from a
  downloaded JPEG is what `docs/DESIGN.md` 3.3 already cost us once.

Output mirrors `candidates.json` so `bin/compose.py` reads both the same
way: `{block: {"subject": ..., "candidates": [...]}}`. Nothing here picks a
photo — `bin/review_page.py` and a person do that.

    python3 bin/fetch_commons.py WBCHET
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.photo_source import _commons, download

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_payload import trip_type   # 同一条「只看开头三个词」的分类规则

WORK = Path("work")
MIN_WIDTH = 1200  # below this a lightbox render (~535–750px CSS) starts to soften


def block_name(day: int, subject: str) -> str:
    """`d07_ulan_hada_volcano` — same shape as the stock blocks."""
    ascii_part = re.sub(r"[^a-z0-9]+", "_", subject.lower()).strip("_")
    return f"d{day:02d}_{ascii_part[:34] or 'subject'}"


def queries_for(subject: str) -> list[str]:
    """Progressively barer forms of the name, longest first.

    The bare-name rule is not something you can apply once and be done with,
    because itinerary titles carry qualifiers. `Ulan Hada Volcano Geopark`
    returns **0** on Commons; drop one word and `Ulan Hada Volcano` returns
    **3**, all GPS-tagged, all genuinely the place. The AND-ish full text
    means every trailing word is another chance to return nothing, so the
    ladder walks the tail off until something answers.

    Stops at two words: a single word like "Grottoes" or "Temple" matches
    half of China and hands a reviewer noise instead of candidates.
    """
    latin = re.sub(r"[^\x00-\x7F]+", " ", subject)
    words = re.sub(r"\s+", " ", latin).strip().split()
    return [" ".join(words[:n]) for n in range(len(words), 1, -1)] or []


def fetch(code: str, per_subject: int = 6) -> dict:
    itinerary = json.loads((WORK / code / "itinerary.json").read_text("utf-8"))
    dest_dir = WORK / code / "cand_commons"
    out: dict[str, dict] = {}

    for section in itinerary["sections"]:
        day = section["day"]
        for item in section.get("trip_items", []):
            title = item["title"]["en"]
            # 交通/入住卡不需要景点图。用 make_payload 那条同样的「只看开头三个词」
            # 规则,免得「Arrival and Hotel Check-In」搜回 6 张泛化机场照,
            # 让签字的人白看一轮。
            if trip_type(title) in ("Transportation", "Accommodation"):
                continue
            subject = item.get("photo_subject") or title
            ladder = queries_for(subject)
            if not ladder:
                continue
            key = block_name(day, ladder[0])
            if key in out:
                continue
            hits, query = [], ladder[0]
            for attempt in ladder:
                try:
                    hits = _commons(attempt, per_subject)
                except Exception as exc:                   # noqa: BLE001
                    print(f"  !! {key}: {exc}")
                    hits = []
                if hits:
                    query = attempt
                    break

            rows = []
            for n, cand in enumerate(hits, start=1):
                if cand.width and cand.width < MIN_WIDTH:
                    continue
                path = dest_dir / f"{key}_{n}.jpg"
                try:
                    if not path.exists():
                        download(cand.url, path)
                except Exception as exc:                   # noqa: BLE001
                    print(f"  !! {key} #{n} download: {exc}")
                    continue
                rows.append({
                    "n": n, "url": cand.url, "source": "commons",
                    "title": cand.title, "path": str(path),
                    "license": cand.license, "credit": cand.credit,
                    "lat": cand.lat, "lon": cand.lon,
                })
            # `query_full` vs `query`:退化过的块要在审核页上显示出来。
            # 退化保证的是「有结果」,不是「结果对」——`Optional Desert Activities
            # and Return to Ordos` 一路退到 `Optional Desert` 也能返回 6 张,
            # 但那 6 张和这个行程没有任何关系。看图的人必须知道搜的是什么词。
            out[key] = {"subject": subject, "query": query,
                        "query_full": ladder[0], "shrunk": query != ladder[0],
                        "day": day, "candidates": rows}
            geo = sum(1 for r in rows if r["lat"] is not None)
            shrunk = "" if query == ladder[0] else f"  ←退化搜 {query!r}"
            flag = "   ← 0" if not rows else ""
            print(f"  {key:<40} {len(rows)} 张 (带坐标 {geo}){flag}{shrunk}")

    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    for code in argv[1:]:
        print(f"== {code}")
        blocks = fetch(code)
        path = WORK / code / "commons.json"
        path.write_text(json.dumps(blocks, indent=2, ensure_ascii=False))
        total = sum(len(b["candidates"]) for b in blocks.values())
        filled = sum(1 for b in blocks.values() if b["candidates"])
        print(f"{code}: {total} 张候选,覆盖 {filled}/{len(blocks)} 个主体 → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
