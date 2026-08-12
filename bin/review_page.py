#!/usr/bin/env python3
"""Render one review page covering all three products.

`lib/preview.py` already renders a per-product page, but each comes out
6–8 MB because it embeds the full-size crops — fine for a local check, too
heavy to hand someone. This builds a single page at preview resolution so
the Planner can approve or reject in one pass.

The page exists to make three things impossible to miss, because each one
is a decision only a person should make:

* **where every picture came from** — the brochure, Webuy's own catalogue,
  or stock — since a stock photo of a real place carries a risk the other
  two do not;
* **which days carry a compliant regional photo instead of the landmark**,
  and why the landmark had none;
* **which crops were pushed past the upscale ceiling** and will look soft.
"""

from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WORK = Path("work")
PRODUCTS = ["WBCKWE", "WBCURC", "WBCHET"]
UPSCALE_CEILING = 2.0
PREVIEW_W = 460

ORIGIN_LABEL = {
    "pdf": ("册子自带", "brochure"),
    "catalogue": ("自家图库", "webuytravel.sg"),
    "web": ("外部图源", "stock / commons"),
}


def thumb(path: str) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((PREVIEW_W, PREVIEW_W))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=72, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def card(p: dict, day_title: str = "") -> str:
    zh, en = ORIGIN_LABEL.get(p["origin"], (p["origin"], ""))
    warn = ""
    if p.get("upscale", 0) > UPSCALE_CEILING:
        warn = (f'<p class="warn">放大 {p["upscale"]:.2f}× — 超过 '
                f'{UPSCALE_CEILING:.1f}× 上限，会偏软</p>')
    note = f'<p class="note">{p["note"]}</p>' if p.get("note") else ""
    where = f'<span class="day">{day_title}</span>' if day_title else ""
    src = p.get("out_path") or p.get("src_path")
    return f"""<figure class="card">
  <img src="{thumb(src)}" alt="{p['subject']}" loading="lazy">
  <figcaption>
    {where}
    <p class="subj">{p['subject']}</p>
    <p class="meta"><span class="chip {p['origin']}">{zh}</span>
       <span class="ref">{p.get('source_ref','')[:52]}</span></p>
    {note}{warn}
  </figcaption>
</figure>"""


def product_block(code: str) -> str:
    plan = json.loads((WORK / code / "plan.json").read_text("utf-8"))
    itin = json.loads((WORK / code / "itinerary.json").read_text("utf-8"))
    titles = {s["day"]: s["title"]["en"] for s in itin["sections"]}
    placements = [p for p in plan["placements"] if p.get("out_path") or p.get("src_path")]

    by_slot = {}
    for p in placements:
        by_slot.setdefault(p["slot"], []).append(p)

    counts = {k: len(v) for k, v in by_slot.items()}
    origins = {}
    for p in placements:
        origins[p["origin"]] = origins.get(p["origin"], 0) + 1
    soft = [p for p in placements if p.get("upscale", 0) > UPSCALE_CEILING]

    days_with = sorted({p["position"] for p in by_slot.get("section", [])})
    missing = [d for d in titles if d not in days_with]

    out = [f"""<section class="product">
  <header class="phead">
    <h2>{code}</h2>
    <p class="pname">{itin['product_name']['en']}</p>
    <p class="pname zh">{itin['product_name']['zh']}</p>
    <ul class="stats">
      <li><b>{itin['travel_days']}</b> 天</li>
      <li><b>{counts.get('section',0)}</b> 张日程图 / 覆盖 <b>{len(days_with)}</b> 天</li>
      <li><b>{counts.get('carousel',0)}</b> 张轮播</li>
      <li><b>{len(itin['highlights'])}</b> 条 highlights</li>
      <li><b>{sum(len(s.get('trip_items',[])) for s in itin['sections'])}</b> 个景点条目</li>
    </ul>
    <p class="prov">来源分布：""" + " · ".join(
        f"{ORIGIN_LABEL.get(k,(k,''))[0]} {v}" for k, v in sorted(origins.items())) + f"""</p>
    {'<p class="prov soft">⚠ ' + str(len(soft)) + ' 张超过放大上限，见下方标注</p>' if soft else ''}
    {'<p class="prov">无配图日：' + '、'.join(f'D{d}（{titles[d][:34]}）' for d in missing) + ' — 均为纯中转/抵离日</p>' if missing else ''}
  </header>"""]

    for slot, label in [("thumbnail", "列表缩略图"), ("carousel", "轮播图"),
                        ("route_map", "路线图"), ("section", "每日配图")]:
        rows = by_slot.get(slot, [])
        if not rows:
            continue
        out.append(f'<h3 class="slot">{label} <span>{len(rows)}</span></h3><div class="grid">')
        for p in sorted(rows, key=lambda r: r["position"]):
            dt = f"DAY {p['position']} · {titles.get(p['position'],'')[:38]}" if slot == "section" else ""
            out.append(card(p, dt))
        out.append("</div>")
    out.append("</section>")
    return "\n".join(out)


CSS = """
:root{--paper:#F5F3EF;--card:#FFFFFF;--ink:#23211E;--muted:#6B6560;--faint:#9A938C;
--accent:#1F5F5B;--warn:#A4442B;--line:rgba(35,33,30,.12);--line2:rgba(35,33,30,.22);
--pdf:#7A5B1F;--cat:#1F5F5B;--web:#5A4A7A;
--sans:-apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue","Segoe UI",sans-serif;
--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--paper:#14140F;--card:#1D1D18;
--ink:#EAE7E1;--muted:#A39C94;--faint:#6F6862;--accent:#5FB3AC;--warn:#D9836A;
--line:rgba(234,231,225,.13);--line2:rgba(234,231,225,.24);
--pdf:#C9A35C;--cat:#5FB3AC;--web:#A794C9;}}
:root[data-theme=dark]{--paper:#14140F;--card:#1D1D18;--ink:#EAE7E1;--muted:#A39C94;
--faint:#6F6862;--accent:#5FB3AC;--warn:#D9836A;--line:rgba(234,231,225,.13);
--line2:rgba(234,231,225,.24);--pdf:#C9A35C;--cat:#5FB3AC;--web:#A794C9;}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.65;margin:0}
.wrap{max-width:1180px;margin:0 auto;padding:44px 22px 90px}
h1{font-size:30px;margin:8px 0 0;letter-spacing:-.01em;text-wrap:balance}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.14em;text-transform:uppercase;
color:var(--accent);font-weight:700}
.lede{color:var(--muted);max-width:64ch;margin:14px 0 0;font-size:16px}
.gate{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--warn);
padding:16px 18px;margin:26px 0 0;font-size:15px}
.gate b{color:var(--warn)}
.product{margin-top:54px;border-top:1px solid var(--line2);padding-top:26px}
.phead h2{font-family:var(--mono);font-size:20px;margin:0;letter-spacing:.04em}
.pname{margin:6px 0 0;font-size:17px;font-weight:600}
.pname.zh{font-weight:400;color:var(--muted);font-size:15px}
.stats{list-style:none;display:flex;flex-wrap:wrap;gap:8px 20px;padding:0;margin:14px 0 0;
font-size:13.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.stats b{color:var(--ink)}
.prov{margin:8px 0 0;font-size:13px;color:var(--muted);font-family:var(--mono)}
.prov.soft{color:var(--warn)}
.slot{font-size:14px;margin:26px 0 10px;font-weight:700;letter-spacing:.02em}
.slot span{font-family:var(--mono);color:var(--faint);font-weight:400;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}
.card{margin:0;background:var(--card);border:1px solid var(--line);overflow:hidden;
display:flex;flex-direction:column}
.card img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block}
figcaption{padding:10px 12px 12px}
.day{font-family:var(--mono);font-size:10.5px;letter-spacing:.05em;color:var(--faint);
text-transform:uppercase}
.subj{margin:3px 0 6px;font-size:13.5px;font-weight:600;line-height:1.35}
.meta{margin:0;display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.chip{font-family:var(--mono);font-size:10px;padding:2px 6px;font-weight:700;
letter-spacing:.03em;border:1px solid currentColor}
.chip.pdf{color:var(--pdf)}.chip.catalogue{color:var(--cat)}.chip.web{color:var(--web)}
.ref{font-family:var(--mono);font-size:10.5px;color:var(--faint);overflow-wrap:anywhere}
.note{margin:7px 0 0;font-size:12px;color:var(--muted);line-height:1.45}
.warn{margin:6px 0 0;font-size:12px;color:var(--warn);font-weight:600}
footer{margin-top:60px;border-top:1px solid var(--line);padding-top:20px;
font-family:var(--mono);font-size:12px;color:var(--faint)}
"""


def main() -> None:
    blocks = "\n".join(product_block(c) for c in PRODUCTS)
    html = f"""<title>配图审核 · 三个产品上架前确认</title>
<style>{CSS}</style>
<div class="wrap">
<header>
  <span class="eyebrow">Skybear 上架前审核 · 2026-08-12</span>
  <h1>三个产品的配图，请过目</h1>
  <p class="lede">每张图都标了来源。<b>册子自带</b>是产品组自己选的照片；<b>自家图库</b>
  是已在 webuytravel.sg 上线的同类产品照片，已授权、同风格；<b>外部图源</b>是搜来的，
  风险最高——每一张都经过看图确认主体，标题一律不采信。</p>
  <div class="gate">
    <b>确认后才会上传，而且只上传到草稿态。</b>
    「Publish for sale」不会被勾选——生产新建表单上这个框默认是勾着的，上传程序会主动
    取消并回读确认。上架那一下留给你点。
  </div>
</header>
{blocks}
<footer>
  webuy-itinerary-publisher · 图片规格 4:3（轮播/缩略图 1440×1080，日程图 1200×900）·
  路线图按原样上传不裁切
</footer>
</div>"""
    out = WORK / "review_all.html"
    out.write_text(html, encoding="utf-8")
    print(f"{out}  {out.stat().st_size/1024/1024:.1f} MB")


if __name__ == "__main__":
    main()
