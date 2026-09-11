#!/usr/bin/env python3
"""一次性迁移:把 5 个脚本里 8 张 per-product 表抽成 work/<CODE>/editorial.json。

这个脚本在迁移完成之后仍然留着,理由只有一个:**它可重复执行**。它不读当前
工作区的 `bin/*.py`(那些表已经被删了),而是用 `git show <ref>:<path>` 把
**迁移之前**的源码取出来再抽,所以任何人都能重跑一遍、和仓库里的 JSON 逐字节
比对,确认这次迁移没有夹带编辑决策的改动:

    python3 tools/migrate_editorial.py --out /tmp/editorial
    for d in /tmp/editorial/*/; do diff "$d/editorial.json" "work/$(basename $d)/editorial.json"; done

注释一起搬。原表里每条选片上面那几行「为什么是这张」是这个仓库最贵的东西
(哪张图被否掉了、饱和度多少、哪一次线上事故促成了这条规则),JSON 没有注释语法,
所以它们落到 `notes` / `why` 两个字段里 —— 见 docs/EDITORIAL_JSON.md。
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import tokenize
from io import StringIO
from pathlib import Path

DEFAULT_REF = "9b5ef5c"  # PR #3 合入后、本次迁移之前的 origin/main

# itemType 的数字是后端存的值,写进 JSON 的是名字 —— 数字在 JSON 里没有任何
# 线索说明 5 是 FOOD 还是别的什么。
ITEM_TYPE_NAMES = {1: "TRANSPORT", 2: "ACCOMMODATION", 3: "ATTRACTION",
                   4: "OTHERS", 5: "FOOD", 6: "LOCAL_TRANSPORT", 7: "GUIDE"}


# --- 从源码里把「数据 + 贴着它的注释」一起取出来 ------------------------------

class Source:
    """一个 .py 文件:AST 用来取值,token 流用来取注释。"""

    def __init__(self, text: str):
        self.text = text
        self.tree = ast.parse(text)
        # lineno -> 注释正文(去掉 '#')。同一行尾部的注释也在这里。
        self.comment_at: dict[int, str] = {}
        # 独占一行的注释,用来判断「上面连续几行都是注释」
        self.own_line: set[int] = set()
        lines = text.splitlines()
        for tok in tokenize.generate_tokens(StringIO(text).readline):
            if tok.type != tokenize.COMMENT:
                continue
            lineno = tok.start[0]
            self.comment_at[lineno] = tok.string.lstrip("#").strip()
            if not lines[lineno - 1][:tok.start[1]].strip():
                self.own_line.add(lineno)

    def table(self, name: str) -> ast.Dict:
        for node in self.tree.body:
            if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == name):
                return node.value
        raise SystemExit(f"表 {name} 不在这个源文件里")

    def lead(self, node: ast.AST) -> list[str]:
        """紧贴在 node 上面那一段连续的整行注释,按原顺序。"""
        out, line = [], node.lineno - 1
        while line in self.own_line:
            out.append(self.comment_at[line])
            line -= 1
        return list(reversed(out))

    def trail(self, node: ast.AST) -> list[str]:
        """node 所在行尾部的注释(`"WBCHET": (...),  # 山西`)。"""
        end = getattr(node, "end_lineno", node.lineno)
        text = self.comment_at.get(end)
        return [text] if text and end not in self.own_line else []

    def notes(self, node: ast.AST) -> list[str]:
        return self.lead(node) + self.trail(node)


def entries(src: Source, name: str):
    """遍历一张以产品代码为键的表,交出 (code, 值节点, 这个键上的注释)。"""
    table = src.table(name)
    for key, value in zip(table.keys, table.values):
        yield ast.literal_eval(key), value, src.notes(key)


def rows(src: Source, seq):
    """遍历一个列表,交出 (literal 值, 这一条上的注释)。"""
    for element in seq.elts:
        yield ast.literal_eval(element), src.notes(element)


def why(notes: list[str]) -> dict:
    return {"why": " ".join(notes)} if notes else {}


def _ref_fields(kind: str, ref) -> dict:
    """把源码里的 (kind, ref) 二元组摊平成 JSON 里的具名字段。"""
    if kind in ("stock", "commons"):
        block, n = ref
        return {"source": kind, "block": block, "n": n}
    if kind == "cat":
        return {"source": "cat", "image_id": ref}
    if kind == "file":
        return {"source": "file", "path": ref}
    raise SystemExit(f"未知的图源 {kind!r}")


# 源码里有三处注释写在了**下一个**产品的键上面:作者写完 WBCKG6 那一块之后
# 接着往下写,两段之间没有空行,所以「上面连续几行注释」这条规则把它们一并算给了
# 后面那个产品。逐条核对出来的三处,搬回它们真正描述的产品:
#     (落错的产品, 字段): (实际描述的产品, 前多少行属于它)
NOTE_PREFIX_BELONGS_TO = {
    ("ACKMG12T", "section_overrides"): ("WBCKG6", 2),
    ("ACKMG12T", "trip_picks"): ("WBCKG6", 9),
    ("WBSZX1", "section_overrides"): ("WBINC9", 6),
}


# --- 8 张表,各自搬到 editorial.json 的哪个字段 --------------------------------

def add_note(doc: dict, field: str, notes: list[str]) -> None:
    if notes:
        doc.setdefault("notes", {}).setdefault(field, []).extend(notes)


def migrate(ref: str) -> dict[str, dict]:
    def source(path: str) -> Source:
        proc = subprocess.run(["git", "show", f"{ref}:{path}"],
                              capture_output=True, text=True, check=True)
        return Source(proc.stdout)

    compose = source("bin/compose.py")
    payload = source("bin/make_payload.py")
    api = source("bin/make_api_payload.py")
    commons = source("bin/fetch_commons.py")
    stock = source("bin/fetch_stock.py")

    docs: dict[str, dict] = {}

    def doc(code: str) -> dict:
        return docs.setdefault(code, {"code": code})

    # PRODUCTS —— region + 图库可采的兄弟产品
    for code, value, notes in entries(compose, "PRODUCTS"):
        region, tours = ast.literal_eval(value)
        d = doc(code)
        d["region"] = region
        d["catalogue_tours"] = tours
        add_note(d, "catalogue_tours", notes)

    # fetch_commons.REGION_BOX —— 「主体对、地方不对」的唯一机械检查
    for code, value, notes in entries(commons, "REGION_BOX"):
        d = doc(code)
        d["commons_region_box"] = list(ast.literal_eval(value))
        add_note(d, "commons_region_box", notes)

    # fetch_stock.STOCK_REGION —— 交给图库搜索的地区词
    for code, value, notes in entries(stock, "STOCK_REGION"):
        d = doc(code)
        d["stock_region"] = ast.literal_eval(value)
        add_note(d, "stock_region", notes)

    # HOUSE_HIGHLIGHTS 两张表(表单那条路 7 个产品、接口那条路 1 个)合成一张。
    # 两边键集不相交,形状也一模一样 —— 同一件事:房子版式的 6 行 highlights。
    for src in (payload, api):
        for code, value, notes in entries(src, "HOUSE_HIGHLIGHTS"):
            d = doc(code)
            d["highlights"] = [{"en": en, "zh": zh, **why(note)}
                               for (en, zh), note in rows(src, value)]
            add_note(d, "highlights", notes)

    # make_api_payload.MEALS —— 逐日餐食,册子页脚抄下来的
    for code, value, notes in entries(api, "MEALS"):
        d = doc(code)
        d["meals"] = {str(day): {"en": en, "zh": zh}
                      for day, (en, zh) in ast.literal_eval(value).items()}
        add_note(d, "meals", notes)

    # make_api_payload.TRIP_TYPES —— 键是 (天, 当天第几条)。原表的值是
    # TRANSPORT / FOOD 这些常量名,JSON 里也写名字:数字落到 JSON 里就再没有
    # 任何线索说明 5 是 FOOD 还是别的什么。
    for code, value, notes in entries(api, "TRIP_TYPES"):
        d = doc(code)
        out_types = {}
        for key, kind in zip(value.keys, value.values):
            day, index = ast.literal_eval(key)
            name = kind.id if isinstance(kind, ast.Name) else ITEM_TYPE_NAMES[
                ast.literal_eval(kind)]
            out_types[f"{day}:{index}"] = name
        d["trip_types"] = out_types
        add_note(d, "trip_types", notes)

    # compose.OVERRIDES —— section 层逐日指定
    for code, days, notes in entries(compose, "OVERRIDES"):
        d = doc(code)
        out: dict[str, list] = {}
        for key, value in zip(days.keys, days.values):
            day_notes = compose.notes(key)
            picks: list[dict] = []
            for (kind, ref_, note), own in rows(compose, value):
                head = day_notes + own if not picks else own
                picks.append({**_ref_fields(kind, ref_), "note": note, **why(head)})
            out[ast.literal_eval(key)] = picks
        d["section_overrides"] = out
        add_note(d, "section_overrides", notes)

    # compose.TRIP_PICKS —— 景点卡专用选片
    for code, value, notes in entries(compose, "TRIP_PICKS"):
        d = doc(code)
        d["trip_picks"] = [{**_ref_fields(kind, ref_), "note": note, **why(own)}
                           for (kind, ref_, note), own in rows(compose, value)]
        add_note(d, "trip_picks", notes)

    # compose.CAROUSEL —— 显式指定的轮播
    for code, value, notes in entries(compose, "CAROUSEL"):
        d = doc(code)
        picks = []
        for (block, n, note), own in rows(compose, value):
            is_cat = block.startswith("cat:")
            picks.append({**_ref_fields("cat" if is_cat else "stock",
                                        block[4:] if is_cat else (block, n)),
                          "note": note, **why(own)})
        d["carousel"] = picks
        add_note(d, "carousel", notes)

    for (wrong, field), (right, count) in NOTE_PREFIX_BELONGS_TO.items():
        lines = docs[wrong]["notes"][field]
        docs[wrong]["notes"][field] = lines[count:]
        add_note(doc(right), field, lines[:count])

    return docs


# 字段顺序固定:读的人从「这是哪个产品」看到「这个产品怎么选片」。
FIELD_ORDER = ["code", "region", "notes", "catalogue_tours", "commons_region_box",
               "stock_region", "highlights", "meals", "trip_types",
               "section_overrides", "trip_picks", "carousel"]


def ordered(doc: dict) -> dict:
    return {k: doc[k] for k in FIELD_ORDER if k in doc}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default=DEFAULT_REF,
                    help="迁移之前的 git ref,表还在源码里的那个提交")
    ap.add_argument("--out", type=Path, default=Path("work"),
                    help="写到哪里,每个产品一个 <CODE>/editorial.json")
    args = ap.parse_args()

    docs = migrate(args.ref)
    for code, doc in sorted(docs.items()):
        dest = args.out / code / "editorial.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(ordered(doc), ensure_ascii=False, indent=2) + "\n",
                        "utf-8")
        print(f"{code}: {dest}")
    print(f"共 {len(docs)} 个产品")


if __name__ == "__main__":
    main()
