"""Render an image plan as a page the Planner signs off before upload.

This is the human gate in the middle of the flow. Nothing reaches Skybear
until someone has looked at this page and said yes, and nothing reaches the
public site until someone has separately ticked *Publish for sale* — see
`skills/skybear-publish-gate/SKILL.md`.

The page is deliberately blunt about provenance and about the numbers that
predict how an image will look once the product page crops it: which slot,
where it came from, how far it was upscaled, and — for the hero — what the
wide crop will actually show.
"""

from __future__ import annotations

import base64
import html
from pathlib import Path

from .image_plan import ImagePlan

_CSS = """
:root { color-scheme: light dark; --bg:#fff; --fg:#16181d; --muted:#5b6270;
        --line:#e3e6ec; --card:#fafbfc; --warn:#a8571b; --warnbg:#fdf3e7;
        --ok:#1c6b3f; --okbg:#eaf6ef; --gap:#8a2b2b; --gapbg:#fbeded; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#14161a; --fg:#e8eaee; --muted:#9aa2b1; --line:#2a2f38;
          --card:#1b1e24; --warn:#e0a465; --warnbg:#2e2415; --ok:#7fd0a1;
          --okbg:#16281e; --gap:#f0908f; --gapbg:#2e1a1a; } }
:root[data-theme="dark"] {
  --bg:#14161a; --fg:#e8eaee; --muted:#9aa2b1; --line:#2a2f38; --card:#1b1e24;
  --warn:#e0a465; --warnbg:#2e2415; --ok:#7fd0a1; --okbg:#16281e;
  --gap:#f0908f; --gapbg:#2e1a1a; }
:root[data-theme="light"] {
  --bg:#fff; --fg:#16181d; --muted:#5b6270; --line:#e3e6ec; --card:#fafbfc;
  --warn:#a8571b; --warnbg:#fdf3e7; --ok:#1c6b3f; --okbg:#eaf6ef;
  --gap:#8a2b2b; --gapbg:#fbeded; }
* { box-sizing:border-box; }
body { margin:0; padding:32px 24px 80px; background:var(--bg); color:var(--fg);
       font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",system-ui,
       "PingFang SC","Microsoft YaHei",sans-serif; }
.wrap { max-width:1180px; margin:0 auto; }
h1 { font-size:26px; margin:0 0 4px; letter-spacing:-.01em; }
h2 { font-size:17px; margin:38px 0 12px; padding-bottom:7px;
     border-bottom:1px solid var(--line); }
.sub { color:var(--muted); margin:0 0 22px; }
.stats { display:flex; flex-wrap:wrap; gap:10px; margin:0 0 8px; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:8px;
        padding:8px 13px; font-size:13px; }
.stat b { font-size:17px; display:block; }
.grid { display:grid; gap:14px;
        grid-template-columns:repeat(auto-fill,minmax(255px,1fr)); }
.card { border:1px solid var(--line); border-radius:10px; overflow:hidden;
        background:var(--card); }
.card img { width:100%; aspect-ratio:4/3; object-fit:cover; display:block; }
.card .meta { padding:9px 11px; font-size:12.5px; }
.subject { font-weight:650; margin-bottom:3px; }
.dim { color:var(--muted); font-size:11.5px; }
.tag { display:inline-block; font-size:10.5px; font-weight:650; padding:1px 7px;
       border-radius:99px; letter-spacing:.02em; }
.pdf { background:var(--okbg); color:var(--ok); }
.web { background:var(--warnbg); color:var(--warn); }
.soft { background:var(--warnbg); color:var(--warn); }
.gapcard { border:1px dashed var(--gap); background:var(--gapbg); border-radius:10px;
           padding:13px; font-size:13px; color:var(--gap); }
.hero { border:2px solid var(--line); border-radius:10px; overflow:hidden;
        margin-bottom:14px; background:var(--card); }
.hero .band { width:100%; aspect-ratio:3/1; object-fit:cover; display:block; }
.note { color:var(--muted); font-size:12px; margin-top:4px; }
table { border-collapse:collapse; width:100%; font-size:13px; }
th,td { text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); }
th { color:var(--muted); font-weight:600; font-size:11.5px;
     text-transform:uppercase; letter-spacing:.04em; }
.scroll { overflow-x:auto; }
"""


def _data_uri(path: str | Path) -> str:
    path = Path(path)
    if not path.exists():
        return ""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _card(placement, *, show_band: bool = False) -> str:
    uri = _data_uri(placement.out_path or placement.src_path)
    if not uri:
        return ""
    origin = "pdf" if placement.origin == "pdf" else "web"
    label = "PDF 原图" if origin == "pdf" else "网图"
    soft = (f'<span class="tag soft">放大 {placement.upscale:.2f}×</span>'
            if placement.upscale > 1.7 else "")
    credit = html.escape(placement.credit or placement.source_ref)
    img_class = "band" if show_band else ""
    return f"""<div class="card">
  <img class="{img_class}" src="{uri}" alt="{html.escape(placement.subject)}">
  <div class="meta">
    <div class="subject">{html.escape(placement.subject or '（未识别）')}</div>
    <div><span class="tag {origin}">{label}</span> {soft}</div>
    <div class="dim">{credit} · {placement.bytes // 1024}KB</div>
    {f'<div class="note">{html.escape(placement.note)}</div>' if placement.note else ''}
  </div>
</div>"""


def render(plan: ImagePlan, out_html: str | Path, *, tour_name: str = "") -> Path:
    """Write a self-contained review page. Images are inlined, so the file
    can be sent to a reviewer with nothing else attached."""
    out_html = Path(out_html)
    out_html.parent.mkdir(parents=True, exist_ok=True)

    carousel = sorted(plan.of("carousel"), key=lambda p: p.position)
    sections = sorted(plan.of("section"), key=lambda p: p.position)
    from_pdf = sum(1 for p in plan.placements if p.origin == "pdf")
    from_web = sum(1 for p in plan.placements if p.origin == "web")

    parts = [f"""<div class="wrap">
<h1>{html.escape(plan.type_code)} 配图审核</h1>
<p class="sub">{html.escape(tour_name or plan.region)} · 全部 4:3 · 轮播 1440×1080 · 每日图 1200×900</p>
<div class="stats">
  <div class="stat"><b>{len(plan.placements)}</b>总图数</div>
  <div class="stat"><b>{from_pdf}</b>PDF 原图</div>
  <div class="stat"><b>{from_web}</b>网图补位</div>
  <div class="stat"><b>{len(plan.gaps)}</b>未补齐</div>
</div>"""]

    if carousel:
        hero = carousel[0]
        uri = _data_uri(hero.out_path or hero.src_path)
        parts.append(f"""<h2>产品页 Hero（轮播第 1 张的宽幅裁切预览）</h2>
<div class="hero"><img class="band" src="{uri}" alt="hero"></div>
<p class="note">正式站会把轮播首图裁成约 3:1 的通栏——上图即实际可见范围。</p>""")

    parts.append("<h2>Image Carousel（轮播）</h2><div class='grid'>")
    parts += [_card(p) for p in carousel]
    parts.append("</div>")

    thumbs = plan.of("thumbnail") + plan.of("route_map")
    if thumbs:
        parts.append("<h2>List Thumbnail / Route Map</h2><div class='grid'>")
        parts += [_card(p) for p in thumbs]
        parts.append("</div>")

    if sections:
        parts.append("<h2>每日图（Section Image Grid）</h2><div class='grid'>")
        for placement in sections:
            card = _card(placement)
            parts.append(card.replace('<div class="subject">',
                                      f'<div class="subject">DAY {placement.position} · '))
        parts.append("</div>")

    if plan.gaps:
        parts.append("<h2>仍需补齐</h2><div class='grid'>")
        for gap in plan.gaps:
            where = (f"DAY {gap.position}" if gap.slot == "section"
                     else f"{gap.slot} #{gap.position}")
            subjects = "、".join(gap.subjects[:4]) or "（无候选主题）"
            parts.append(f"""<div class="gapcard"><b>{where}</b><br>
              {html.escape(gap.reason)}<br><span class="dim">建议搜索：
              {html.escape(subjects)}</span></div>""")
        parts.append("</div>")

    parts.append("""<h2>状态</h2><p class="sub">本次上传全部落 <b>unpublished</b>
      （<code>wt_travel.travel_status = 0</code>）。人工审核通过后，由 Planner 在
      Skybear 手动勾选 <b>Publish for sale</b> 才会上线。</p></div>""")

    out_html.write_text(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(plan.type_code)} 配图审核</title>"
        f"<style>{_CSS}</style></head><body>{''.join(parts)}</body></html>",
        encoding="utf-8",
    )
    return out_html
