#!/usr/bin/env python3
"""Fold an itinerary and its image plan into the one blob the form filler eats.

`work/<CODE>/form_payload.json` is what gets injected into the Skybear admin
page: the text side comes straight from `itinerary.json`, the image side is
`plan.json`'s placements regrouped by slot.

Images are carried as **absolute local paths**, not URLs. The first cut of this
file pointed at `http://127.0.0.1:8777/...` on the theory that a loopback origin
is exempt from mixed-content blocking. It is not, at least not for `fetch`:
called from the https admin page the promise neither resolves nor rejects and
the console stays clean, so the failure looks like a hang rather than a block.
Paths let the upload go through the extension's file input instead, which never
touches the page's network stack.

The crops themselves live under `work/<CODE>/out/` and are gitignored, so they
only exist in a checkout that has actually run `bin/compose.py`. `--assets-root`
points at that checkout when this runs from a worktree.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SLOTS = ("carousel", "carousel_mobile", "thumbnail", "route_map", "section",
         "trip")

# Trip Type is a required el-select on every trip item, and the itinerary has
# no such field — the brochures describe what you see, not how it is filed.
# The vocabulary is Skybear's, fixed at seven values; only two of them ever
# apply to a landmark card, and the split is whether the day's entry is a
# place you stop at or a leg you travel. Everything that is not a movement is
# an attraction, which is the safe direction to be wrong in: a mislabelled
# attraction is invisible on the page, a mislabelled transfer is not.
_TRANSPORT = re.compile(
    r"\b(arrival|arrive|depart|departure|homeward|transfer|airport|flight|"
    r"on to|back to|onward|bound|coach to|return to|travel to|drive to)\b", re.I)
_FOOD = re.compile(r"\b(banquet|dinner|lunch|breakfast|tasting|cuisine)\b", re.I)
_STAY = re.compile(r"\b(check[- ]?in|hotel|resort|overnight)\b", re.I)


# The Highlight block is exactly six bilingual rows. Not a form limitation to
# work around — six is the house format. `webuytravel.sg/tours/115`, the direct
# style peer of this batch, publishes exactly six (read live 2026-08-13), laid
# out as four headline lines then two cuisine lines packed with "·":
#
#     Xiaoqikong and Mount Fanjing, both UNESCO World Heritage sites
#     Huangguoshu Waterfall, Asia's largest waterfall
#     Explore geological wonders at Maling River Canyon, Wanfenglin, ...
#     Enjoy a complimentary Miao costume experience
#     Qian Cuisine · Sour Soup Fish · Canyon Flavors · Miao Cuisine
#     Wild Mushroom Cuisine · Long Table Banquet · Grilled Fish Specialty
#
# The itineraries carry 15–22 highlights, one per city plus one per dish, which
# is the right shape for a brochure and the wrong shape for this block. Folding
# them is an editorial call, so it lives here in full rather than being derived:
# the per-dish lines collapse into the two cuisine rows losing nothing, and the
# per-city lines are ranked by draw, so what falls off the end is the weakest.
# The meal-count and hotel-grade lines are dropped because the reference page
# does not carry them — meals already appear on every day of the itinerary.
HOUSE_HIGHLIGHTS = {
    "WBCKWE": [
        ("Mount Fanjing, a UNESCO World Heritage site",
         "梵净山，世界自然遗产"),
        ("Huangguoshu Waterfall, Asia’s largest waterfall",
         "黄果树大瀑布，亚洲最大瀑布"),
        ("Explore geological wonders at Maling River Canyon, Wanfenglin and Wanfeng Lake",
         "探访马岭河大峡谷、万峰林、万峰湖地质奇观"),
        ("Complimentary Miao costume experience at Xijiang Qianhu Miao Village",
         "西江千户苗寨，赠送苗服换装体验"),
        ("Highland Flavors · Qian (Guizhou) Cuisine · Canyon Flavors · Buyi Ethnic Flavors",
         "高原风味 · 黔菜风味 · 峡谷风味 · 布依风味"),
        ("Wild Mushroom Cuisine · Sour Soup Flavors · Miao Long-Table Banquet",
         "菌子风味 · 酸汤风味 · 长桌宴"),
    ],
    "WBCURC": [
        ("Kanas Lake, Kanas Three Bays and Hemu Village — pristine alpine lakes and forests",
         "喀纳斯湖、喀纳斯三湾与禾木村 — 高山湖泊与原始森林"),
        ("Duku Highway scenic drive along the Tianshan mountain road",
         "独库公路景观之旅，穿越天山公路风光"),
        ("Nalati Sky Grassland with a Kazakh grassland bonfire party",
         "那拉提空中草原，草原篝火晚会与哈萨克草原文化"),
        ("Sayram Lake · Keketuohai · Urho Ghost City · Flaming Mountains and the Karez wells of Turpan",
         "赛里木湖 · 可可托海 · 乌尔禾魔鬼城 · 火焰山与吐鲁番坎儿井"),
        ("Xinjiang Big Plate Chicken · Hand-Pulled Rice · Nang Pit-Roasted Meat · Lamb Skewers",
         "大盘鸡风味 · 新疆手抓饭 · 馕坑肉 · 新疆羊肉串风味"),
        ("Whole Roasted Lamb Feast · Xinjiang Song-and-Dance Banquet · Xinjiang Mini Hot Pot",
         "烤全羊风味宴 · 新疆歌舞宴 · 新疆小火锅风味"),
    ],
    # WBSZX1 册子原始 18 条:1 条餐数、10 条菜式/餐厅、1 条酒店钻级、6 条按城市
    # 分组的景点。这是一个美食团,所以两条餐食行要吃下全部 10 条,而不是像其他
    # 产品那样只压缩风味名;番禺四海一家和南海渔村·天空一号是餐厅不是菜式,但
    # 在粤港澳客群里本身就是卖点,予以保留。
    # 落掉的:餐数、4 钻酒店(参考页版式不带),以及深圳湾人才公园、顺峰山大牌坊、
    # 欢乐海岸、陈皮村、咀香园/罗西尼博物馆、深中通道 —— 都在逐日行程里出现。
    "WBSZX1": [
        ("Eight cities in one journey: Shenzhen · Shunde · Foshan · Qingyuan · "
         "Guangzhou · Jiangmen · Zhongshan · Zhuhai",
         "一程八城:深圳 · 顺德 · 佛山 · 清远 · 广州 · 江门 · 中山 · 珠海"),
        ("Guangzhou — Canton Tower, Huacheng Square, Shawan Ancient Town and a "
         "luxury Pearl River night cruise",
         "广州 — 广州塔、花城广场、沙湾古镇与豪华珠江夜游"),
        ("Foshan Ancestral Temple · Wong Fei-hung Memorial Hall · Lingnan Tiandi · "
         "Romance of Guangdong live show · Huangtengxia Glass Bridge",
         "佛山祖庙 · 黄飞鸿纪念馆 · 岭南新天地 · 广东千古情 · 黄腾峡玻璃桥"),
        ("Chikan Ancient Town and 33 Market Street in Jiangmen · Zhuhai's Lovers' "
         "Road, Fisher Girl Statue and Sun and Moon Shell Theatre with the "
         "Shijingshan cable car",
         "江门赤坎古镇与三十三墟街 · 珠海情侣路、渔女像、日月贝大剧院与石景山缆车"),
        ("Shunde Fish Feast · Qingyuan Chicken Feast · Xinhui Roast Goose · "
         "Buddha Jumps Over the Wall",
         "顺德鱼宴 · 清远鸡宴 · 新会烧鹅 · 佛跳墙宴"),
        ("Cantonese Dim Sum Banquet · Steamed Seafood · Kaiping Eel Rice · "
         "Panyu Sihaiyijia · Nanhai Fishing Village Sky One",
         "广府点心宴 · 蒸汽海鲜 · 开平黄鳝饭 · 番禺四海一家 · 南海渔村·天空一号"),
    ],
    # WBINC9 册子原始 17 条:1 条餐数、8 条菜式、1 条酒店钻级、7 条按城市分组的
    # 景点。折叠后落掉的是宁夏博物馆、览山公园、木活字印刷、青铜峡游船 —— 都在
    # 逐日行程里出现,不占头部版位;餐数和钻级按参考页版式一律不进 highlights。
    "WBINC9": [
        ("Shapotou Scenic Area, where the Yellow River meets the Tengger Desert, "
         "with a night at a desert stargazing camp",
         "沙坡头景区,黄河与腾格里沙漠交汇;入住沙漠观星营地"),
        ("Three-Lake Off-Road Crossing in the Alxa desert — Wulan Lake, Camel Lake "
         "and Guitar Lake, with a complimentary Wulan Lake aerial video",
         "阿拉善三湖越野穿越 — 乌兰湖、骆驼湖、吉他湖,赠送乌兰湖航拍视频"),
        ("Yellow River Stone Forest and the Twenty-Two-Bend scenic route, "
         "a filming location for The Myth",
         "黄河石林与二十二道弯,电影《神话》取景地"),
        ("Western Xia Imperial Tombs · 108 Pagodas · Helan Mountain Rock Art · "
         "Zhenbeipu Western Film Studio · Shuidonggou Underground Troop Caves · "
         "Helan Mountain winery tasting",
         "西夏陵 · 一百零八塔 · 贺兰山岩画 · 镇北堡西部影城 · 水洞沟藏兵洞 · 贺兰山酒庄品酒"),
        ("Hand-Grabbed Mutton · Roasted Squab · Desert Barbecue · "
         "Mutton Hotpot, one individual pot per person",
         "手抓羊肉风味 · 烤乳鸽风味 · 沙漠烧烤 · 涮羊肉风味(每人一小锅)"),
        ("Haozi Noodle · Zhongwei Local Mixed-Snack · Bobo Pork · Cantonese Cuisine",
         "蒿子面风味 · 中卫烩小吃风味 · 饽饽肉风味 · 粤菜风味"),
    ],
    "WBCHET": [
        ("Yungang Grottoes, a UNESCO World Heritage site, and Datong Ancient City",
         "云冈石窟（世界文化遗产）与大同古城"),
        ("The Hanging Temple of Hunyuan and the Yingxian Wooden Pagoda",
         "浑源悬空寺与应县木塔"),
        ("Ordos Grassland welcome ceremony, Mongolian costume experience, bonfire party "
         "and a luxury yurt upgrade",
         "鄂尔多斯草原迎宾仪式、蒙古族服饰换装、草原篝火晚会、豪华蒙古包升级"),
        ("Xiangshawan desert cableway · Ulan Hada Volcano Geopark · Ningwu Wannian Ice Cave "
         "and Hanging Village",
         "响沙湾沙漠索道 · 乌兰哈达火山地质公园 · 宁武万年冰洞与悬空村"),
        ("Hand-Grabbed Mutton · Mutton Hot Pot · Roast Duck · Mongolian Cuisine",
         "手把肉 · 涮羊肉 · 烤鸭 · 蒙古风味"),
        ("Ningwu · Hunyuan · Datong and Yimeng regional specialities",
         "宁武风味 · 浑源风味 · 大同美食 · 伊盟风味"),
    ],
}


def trip_type(title: str) -> str:
    # Only the opening words decide. A movement card leads with the movement
    # ("Coach to Nalati", "Homeward Bound"); when the phrase turns up later the
    # card is about something else and merely ends by going somewhere —
    # "Optional Desert Activities and Return to Ordos" is a desert afternoon,
    # not a transfer, and filing it under Transportation would hide it.
    if _TRANSPORT.search(" ".join(title.split()[:3])):
        return "Transportation"
    if _STAY.search(title):
        return "Accommodation"
    if _FOOD.search(title):
        return "Food"
    return "Attractions"


def build(code: str, work: Path, assets_root: Path) -> dict:
    base = work / code
    itinerary = json.loads((base / "itinerary.json").read_text("utf-8"))
    plan = json.loads((base / "plan.json").read_text("utf-8"))

    images: dict[str, list[dict]] = {slot: [] for slot in SLOTS}
    missing = []
    for placement in plan["placements"]:
        out = placement.get("out_path")
        if not out:
            continue
        path = (assets_root / out).resolve()
        if not path.exists():
            missing.append(str(path))
        row = {
            "pos": placement["position"],
            "path": str(path),
            "bytes": placement.get("bytes"),
            "subject": placement["subject"],
        }
        # trip 图的地址是 (天, 第几张景点卡) —— 光有 pos 到这一层就不唯一了,
        # 上传端要靠 trip_index 找到对应的那张卡。
        if placement["slot"] == "trip":
            row["trip_index"] = placement.get("trip_index") or 0
        images.setdefault(placement["slot"], []).append(row)
    # The portrait carousel is produced by `bin/mobile_crops.py` and is not in
    # the plan — it is the same picks at a second ratio, matched by position.
    for row in images["carousel"]:
        mobile = work / code / "out_mobile" / f"carousel_{row['pos']:02d}_mobile.jpg"
        if mobile.exists():
            images["carousel_mobile"].append({
                "pos": row["pos"],
                "path": str(mobile.resolve()),
                "bytes": mobile.stat().st_size,
                "subject": row["subject"],
            })
        else:
            missing.append(str(mobile))

    for rows in images.values():
        rows.sort(key=lambda r: r["pos"])

    if missing:
        # Loud on purpose: a payload that silently points at absent crops would
        # only surface as an upload that quietly attaches nothing.
        raise SystemExit(f"{code}: {len(missing)} crops missing, first={missing[0]}")

    for section in itinerary["sections"]:
        for item in section.get("trip_items", []):
            item["trip_type"] = trip_type(item["title"]["en"])

    return {
        "type_code": itinerary["type_code"],
        "travel_days": itinerary.get("travel_days"),
        "product_name": itinerary["product_name"],
        "highlights": [{"en": en, "zh": zh} for en, zh in HOUSE_HIGHLIGHTS[code]],
        "highlights_source": itinerary["highlights"],
        "sections": itinerary["sections"],
        "images": images,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*", default=["WBCKWE", "WBCURC", "WBCHET"])
    ap.add_argument("--work", type=Path, default=Path("work"))
    ap.add_argument("--assets-root", type=Path, default=Path("."),
                    help="checkout that holds the materialised work/<CODE>/out/ crops")
    args = ap.parse_args()

    for code in args.codes or ["WBCKWE", "WBCURC", "WBCHET"]:
        payload = build(code, args.work, args.assets_root)
        dest = args.work / code / "form_payload.json"
        dest.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
        counts = " ".join(f"{s}={len(payload['images'].get(s, []))}" for s in SLOTS)
        print(f"{code}: sections={len(payload['sections'])} "
              f"highlights={len(payload['highlights'])} | {counts}")


if __name__ == "__main__":
    main()
