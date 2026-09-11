"""`work/<CODE>/editorial.json` —— 一个产品的全部编辑决策,读取并校验。

这些决策原来是 `bin/*.py` 里 8 张以产品代码为键的字典(约 1352 行)。搬出来的
理由在 issue #4:业务同事跑完一本册子不该产生一次代码改动,两个人同时做两本
册子不该改到同一个字典的相邻行。**跟着产品走**,和 `itinerary.json` /
`plan.json` 同级,而不是一个集中的大文件 —— 集中式只是把合并冲突原样搬过去。

字段清单和写法见 `docs/EDITORIAL_JSON.md`。

## 为什么校验要这么啰嗦

原来的 `OVERRIDES` / `TRIP_PICKS` 是 Python 字面量:键名打错了,`compose.py`
会在解析那一步 `SystemExit`,并且说清是哪个产品、哪个槽位、指向了什么。
这个行为是 2026-08 专门修过的(`docs/DESIGN.md` 6.9 / 6.11 记的两次静默降级:
一个打错的 block 名被 `if row:` 静默跳过,那天就无声地少一张图,而摘要行只报
gap、不说「你指的那张不存在」)。

换成 JSON 之后最容易退化成的就是「键不认识,跳过」。所以这里反过来:
**任何不认识的键、不认识的取值、少掉的必填字段,都在读取那一刻就炸**,
错误信息里带上产品代码和它在文件里的位置。指向不存在的候选那一类由
`bin/compose.py` 在解析引用时炸(它才知道 candidates.json 里有什么),
两道加起来覆盖 issue #4 Done When 第 4 条要的两种情况。
"""

from __future__ import annotations

import json
from pathlib import Path

# 图源。和 `bin/compose.py` 里那四个分支一一对应:
#   stock    work/<CODE>/candidates.json 的 block#n
#   commons  work/<CODE>/commons.json 的 block#n
#   cat      work/catalogue.json 里的 image_id(webuytravel.sg 在售兄弟产品)
#   file     仓库里的一个具体文件路径
REF_FIELDS = {
    "stock": ("block", "n"),
    "commons": ("block", "n"),
    "cat": ("image_id",),
    "file": ("path",),
}
SECTION_SOURCES = set(REF_FIELDS)          # section 层四级都能用
TRIP_SOURCES = {"stock", "commons"}        # 景点卡只从 ③④ 两级取
CAROUSEL_SOURCES = {"stock", "cat"}        # 轮播:图库图 + stock

# `bin/make_api_payload.py` 的 itemType。JSON 里写名字不写数字 —— 数字落到
# JSON 里就再没有任何线索说明 5 是 FOOD 还是别的什么。
ITEM_TYPES = {"TRANSPORT": 1, "ACCOMMODATION": 2, "ATTRACTION": 3, "OTHERS": 4,
              "FOOD": 5, "LOCAL_TRANSPORT": 6, "GUIDE": 7}

FIELDS = {"code", "region", "notes", "catalogue_tours", "commons_region_box",
          "stock_region", "highlights", "meals", "trip_types",
          "section_overrides", "trip_picks", "carousel"}

FILENAME = "editorial.json"


class EditorialError(SystemExit):
    """校验失败。继承 SystemExit,和管线里其它「指错了要炸」的地方同一种退出。"""


def _fail(code: str, where: str, msg: str):
    raise EditorialError(f"work/{code}/{FILENAME} {where}: {msg}")


def path_for(code: str, work: Path) -> Path:
    return work / code / FILENAME


def codes(work: Path) -> list[str]:
    """有 editorial.json 的产品,按代码排序。

    产品清单原来是 `bin/compose.py` 里的 `PRODUCTS`。改成扫目录之后顺序变成
    字典序而不是当初写进源码的顺序 —— 这不影响产出:每个产品各写各的
    `work/<CODE>/plan.json`,产品之间没有共享状态。
    """
    return sorted(p.parent.name for p in work.glob(f"*/{FILENAME}"))


def load(code: str, work: Path) -> dict:
    """读 + 校验。文件不在就炸 —— 这是主线上的必需品。"""
    doc = load_if_present(code, work)
    if doc is None:
        _fail(code, "", f"文件不存在。新产品要先写这一份编辑决策,"
                        f"格式见 docs/EDITORIAL_JSON.md")
    return doc


def load_if_present(code: str, work: Path) -> dict | None:
    """读 + 校验,文件不在就返回 None。

    只有 `bin/fetch_commons.py` / `bin/fetch_stock.py` 用这一支:抓候选图是
    **早于**写编辑决策的一步,新产品跑到那里时这份文件本来就还不存在。缺文件
    的代价(没有 GPS 框、地区词退回 "China")两个脚本各自打印出来。
    """
    dest = path_for(code, work)
    if not dest.exists():
        return None
    try:
        doc = json.loads(dest.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        _fail(code, "", f"不是合法的 JSON —— {exc}")
    validate(code, doc)
    return doc


# --- 校验 --------------------------------------------------------------------

def validate(code: str, doc: dict) -> None:
    if not isinstance(doc, dict):
        _fail(code, "", "顶层要是一个对象")
    unknown = sorted(set(doc) - FIELDS)
    if unknown:
        # 打错的键名在这里就报出来,而不是变成一条被静默忽略的编辑决策。
        _fail(code, "", f"不认识的字段 {unknown} —— 可用字段:{sorted(FIELDS)}")
    if doc.get("code") != code:
        _fail(code, "code", f"写的是 {doc.get('code')!r},和目录名对不上")
    if not isinstance(doc.get("region"), str) or not doc["region"]:
        _fail(code, "region", "要是一个非空字符串,例如 \"CHN\"")

    _check_notes(code, doc.get("notes"))
    _check_tours(code, doc.get("catalogue_tours"))
    _check_box(code, doc.get("commons_region_box"))
    if "stock_region" in doc and not isinstance(doc["stock_region"], str):
        _fail(code, "stock_region", "要是一个字符串,例如 \"Yunnan China\"")
    _check_highlights(code, doc.get("highlights"))
    _check_meals(code, doc.get("meals"))
    _check_trip_types(code, doc.get("trip_types"))

    overrides = doc.get("section_overrides") or {}
    if not isinstance(overrides, dict):
        _fail(code, "section_overrides", "要是一个以 d01 / d02 … 为键的对象")
    for key, picks in overrides.items():
        where = f"section_overrides.{key}"
        if not (isinstance(key, str) and len(key) == 3 and key[0] == "d"
                and key[1:].isdigit()):
            _fail(code, where, "键要写成 d01 / d02 这种两位数的形式")
        _check_picks(code, where, picks, SECTION_SOURCES)

    _check_picks(code, "trip_picks", doc.get("trip_picks") or [], TRIP_SOURCES)
    if "carousel" in doc:
        _check_picks(code, "carousel", doc["carousel"], CAROUSEL_SOURCES)


def _check_notes(code: str, notes) -> None:
    if notes is None:
        return
    if not isinstance(notes, dict):
        _fail(code, "notes", "要是一个「字段名 → 说明行」的对象")
    for field, lines in notes.items():
        if field not in FIELDS:
            _fail(code, f"notes.{field}", f"注解了一个不存在的字段")
        if not isinstance(lines, list) or not all(isinstance(s, str) for s in lines):
            _fail(code, f"notes.{field}", "要是一组字符串")


def _check_tours(code: str, tours) -> None:
    if tours is None:
        _fail(code, "catalogue_tours", "必填。没有可采的兄弟产品就写空数组 []")
    if not isinstance(tours, list) or not all(isinstance(t, str) for t in tours):
        _fail(code, "catalogue_tours", "要是一组 tours/… 字符串")


def _check_box(code: str, box) -> None:
    if box is None:
        return
    if (not isinstance(box, list) or len(box) != 4
            or not all(isinstance(v, (int, float)) for v in box)):
        _fail(code, "commons_region_box",
              "要写成 [lat_min, lat_max, lon_min, lon_max] 四个数")
    if box[0] >= box[1] or box[2] >= box[3]:
        # 上下界写反了会让 in_region 对每一张图都返回 False,而那看起来和
        # 「这批候选全在别的大洲」一模一样。
        _fail(code, "commons_region_box",
              f"上下界反了:{box} —— 顺序是 lat_min, lat_max, lon_min, lon_max")


def _check_bilingual(code: str, where: str, row) -> None:
    if not isinstance(row, dict):
        _fail(code, where, "要是一个 {\"en\": …, \"zh\": …} 对象")
    missing = [k for k in ("en", "zh") if not isinstance(row.get(k), str)]
    if missing:
        # zh 写成 cn 是这个项目上反复出现的一种错(UPLOAD_RUNBOOK 第 3 条红线:
        # 写错会静默失效,直到保存时才报验证错误)。这里提前炸掉。
        _fail(code, where, f"缺 {missing} —— 中文的键是 zh 不是 cn")
    extra = sorted(set(row) - {"en", "zh", "why"})
    if extra:
        _fail(code, where, f"不认识的字段 {extra}")


def _check_highlights(code: str, highlights) -> None:
    if highlights is None:
        return
    if not isinstance(highlights, list):
        _fail(code, "highlights", "要是一组 {\"en\": …, \"zh\": …}")
    if len(highlights) != 6:
        # 6 是房子版式,不是表单限制(UPLOAD_RUNBOOK 第 5 步第 4 条)。
        _fail(code, "highlights", f"有 {len(highlights)} 条,房子版式是 6 条")
    for i, row in enumerate(highlights):
        _check_bilingual(code, f"highlights[{i}]", row)


def _check_meals(code: str, meals) -> None:
    if meals is None:
        return
    if not isinstance(meals, dict):
        _fail(code, "meals", "要是一个「天 → {en, zh}」的对象")
    for day, row in meals.items():
        if not (isinstance(day, str) and day.isdigit()):
            _fail(code, f"meals.{day}", "键是天数,写成 \"1\" \"2\" 这样的字符串")
        _check_bilingual(code, f"meals.{day}", row)


def _check_trip_types(code: str, types) -> None:
    if types is None:
        return
    if not isinstance(types, dict):
        _fail(code, "trip_types", "要是一个「\"天:第几条\" → 类型名」的对象")
    for key, name in types.items():
        where = f"trip_types.{key!r}"
        parts = str(key).split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            _fail(code, where, "键写成 \"4:2\" —— 第 4 天、当天第 2 条(从 0 数)")
        if name not in ITEM_TYPES:
            _fail(code, where,
                  f"不认识的类型 {name!r} —— 可用:{sorted(ITEM_TYPES)}")


def _check_picks(code: str, where: str, picks, allowed: set[str]) -> None:
    if not isinstance(picks, list):
        _fail(code, where, "要是一组选片")
    for i, pick in enumerate(picks):
        spot = f"{where}[{i}]"
        if not isinstance(pick, dict):
            _fail(code, spot, "要是一个对象")
        source = pick.get("source")
        if source not in allowed:
            _fail(code, spot,
                  f"不认识的图源 {source!r} —— 这个槽位可用:{sorted(allowed)}")
        required = REF_FIELDS[source]
        for field in required:
            if field not in pick:
                _fail(code, spot, f"{source} 少了 {field!r}")
        if source in ("stock", "commons"):
            if not isinstance(pick["block"], str) or not pick["block"]:
                _fail(code, spot, "block 要是一个非空字符串")
            if not isinstance(pick["n"], int) or isinstance(pick["n"], bool):
                _fail(code, spot, f"n 要是整数,收到 {pick['n']!r}")
        else:
            if not isinstance(pick[required[0]], str) or not pick[required[0]]:
                _fail(code, spot, f"{required[0]} 要是一个非空字符串")
        if not isinstance(pick.get("note", ""), str):
            _fail(code, spot, "note 要是字符串")
        extra = sorted(set(pick) - {"source", "note", "why"} - set(required))
        if extra:
            # 把 n 写在 cat 条目上、或者 image_id 写在 stock 条目上,都是在这里炸。
            _fail(code, spot, f"{source} 用不到的字段 {extra}")


# --- 取用:交给脚本的形状 -----------------------------------------------------
#
# 下面几个函数把 JSON 摊回 `bin/compose.py` 原来直接写在源码里的元组形状。
# 这样做是刻意的:本次迁移要证明的是**等价变换**(issue #4 Done When 第 1 条,
# 17 个产品的 plan.json 逐字节比对),所以选片逻辑一行都不动,只换数据来源。

def _ref(pick: dict):
    source = pick["source"]
    if source in ("stock", "commons"):
        return (pick["block"], pick["n"])
    return pick[REF_FIELDS[source][0]]


def section_overrides(doc: dict) -> dict:
    """`{"d02": [(kind, ref, note), …]}`。"""
    return {day: [(p["source"], _ref(p), p.get("note", "")) for p in picks]
            for day, picks in (doc.get("section_overrides") or {}).items()}


def trip_picks(doc: dict) -> list:
    """`[(kind, (block, n), note), …]`。"""
    return [(p["source"], _ref(p), p.get("note", ""))
            for p in doc.get("trip_picks") or []]


def carousel(doc: dict) -> list | None:
    """`[(block, n, note), …]`,没写就是 None —— 走自动补齐那条路。

    `None` 和 `[]` 在 `fill_carousel` 里是两件事:前者自动从图库剩图里补,
    后者是「这个产品的轮播明确留空」。所以这里不能把缺字段折成空列表。
    """
    if "carousel" not in doc:
        return None
    return [("cat:" + p["image_id"], 0, p.get("note", "")) if p["source"] == "cat"
            else (p["block"], p["n"], p.get("note", ""))
            for p in doc["carousel"]]


def highlights(code: str, doc: dict) -> list:
    """`[(en, zh), …]` 六条。缺就炸:这是编辑决策,不能让册子的十几条原样漏过去。"""
    rows = doc.get("highlights")
    if rows is None:
        _fail(code, "highlights",
              "没有 highlights。表单只有 6 行,它们是编辑决策 —— 上传前先写好,"
              "不要让册子的 15–22 条原样漏过去")
    return [(row["en"], row["zh"]) for row in rows]
