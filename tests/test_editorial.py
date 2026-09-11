"""`work/<CODE>/editorial.json` 的校验,和「指错了要炸」这条不变式。

这批测试守的是 issue #4 Invariants 里最容易在换成 JSON 之后悄悄退化的那一条:
**指错了要炸,不许静默跳过。** 换之前那是 Python 字面量,写错一个 block 名会
`SystemExit`;换之后最自然的写法恰恰是 `data.get(key)` 然后一个 `if row:` ——
那就是 `docs/DESIGN.md` 6.9 / 6.11 记的两次静默降级:那天无声地少一张图,
摘要行只报 gap,不说「你指的那张不存在」,而签字的人在审核页上根本看不见它。

两种错法各自有闸:
  * 键名/取值打错          → `lib.editorial` 在读取时炸(schema)
  * 指向一个不存在的候选    → `bin/compose.py` 在解析引用时炸(只有它知道
                             candidates.json / commons.json 里有什么)
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

from lib import editorial

import compose  # noqa: E402  (要先把 bin/ 放进 sys.path)


MINIMAL = {
    "code": "WBTEST",
    "region": "CHN",
    "catalogue_tours": [],
    "section_overrides": {},
    "trip_picks": [],
}


def write(tmp_path: Path, doc: dict, code: str = "WBTEST") -> Path:
    dest = tmp_path / code
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "editorial.json").write_text(json.dumps(doc, ensure_ascii=False), "utf-8")
    return tmp_path


def load(tmp_path: Path, **overrides):
    doc = {**MINIMAL, **overrides}
    return editorial.load("WBTEST", write(tmp_path, doc))


# --- 一份写对的文件读得出来 --------------------------------------------------

def test_a_well_formed_file_loads(tmp_path):
    doc = load(tmp_path,
               section_overrides={"d03": [{"source": "stock", "block": "d03_x",
                                           "n": 2, "note": "看过"}]},
               trip_picks=[{"source": "commons", "block": "d03_x", "n": 1,
                            "note": "看过"}])
    assert editorial.section_overrides(doc) == {
        "d03": [("stock", ("d03_x", 2), "看过")]}
    assert editorial.trip_picks(doc) == [("commons", ("d03_x", 1), "看过")]


def test_no_carousel_key_means_fill_it_automatically(tmp_path):
    # `None` 和 `[]` 在 fill_carousel 里是两件事:前者从图库剩图里自动补,
    # 后者是「这个产品的轮播明确留空」。折成空列表会静默改掉三个产品的轮播。
    assert editorial.carousel(load(tmp_path)) is None
    assert editorial.carousel(load(tmp_path, carousel=[])) == []


def test_the_seventeen_shipped_products_all_validate():
    # 已经签过字的那 17 个产品必须一直读得过 —— 这条挂了说明 schema 收紧到了
    # 把既有编辑决策判成非法,那是比漏检更糟的方向。
    work = Path("work")
    codes = editorial.codes(work)
    assert len(codes) == 17
    for code in codes:
        assert editorial.load(code, work)["code"] == code


# --- 第一种错法:键名 / 取值打错,读取时就炸 ---------------------------------

def test_an_unknown_top_level_key_is_refused(tmp_path):
    with pytest.raises(SystemExit) as exc:
        load(tmp_path, section_override={})      # 少了一个 s
    assert "section_override" in str(exc.value)
    assert "WBTEST" in str(exc.value)


def test_an_unknown_source_name_is_refused(tmp_path):
    with pytest.raises(SystemExit) as exc:
        load(tmp_path, section_overrides={
            "d03": [{"source": "stok", "block": "d03_x", "n": 1}]})
    message = str(exc.value)
    assert "'stok'" in message                    # 指向了什么
    assert "section_overrides.d03[0]" in message  # 哪个槽位
    assert "WBTEST" in message                    # 哪个产品


def test_a_pick_missing_its_index_is_refused(tmp_path):
    with pytest.raises(SystemExit) as exc:
        load(tmp_path, section_overrides={"d03": [{"source": "stock",
                                                   "block": "d03_x"}]})
    assert "'n'" in str(exc.value)


def test_a_catalogue_pick_may_not_carry_a_stock_index(tmp_path):
    # image_id + n 同时出现,说明写的人把两种图源的写法混了。
    with pytest.raises(SystemExit) as exc:
        load(tmp_path, section_overrides={
            "d03": [{"source": "cat", "image_id": "abc", "n": 2}]})
    assert "['n']" in str(exc.value)


def test_the_trip_card_slot_refuses_catalogue_picks(tmp_path):
    # 景点卡只从 ③Commons / ④stock 取。图库图走的是自动匹配那条路。
    with pytest.raises(SystemExit) as exc:
        load(tmp_path, trip_picks=[{"source": "cat", "image_id": "abc"}])
    assert "trip_picks[0]" in str(exc.value)


def test_a_day_key_that_is_not_dNN_is_refused(tmp_path):
    with pytest.raises(SystemExit) as exc:
        load(tmp_path, section_overrides={"d3": []})
    assert "section_overrides.d3" in str(exc.value)


def test_highlights_must_be_exactly_six(tmp_path):
    with pytest.raises(SystemExit) as exc:
        load(tmp_path, highlights=[{"en": "a", "zh": "甲"}])
    assert "6" in str(exc.value)


def test_a_chinese_key_written_as_cn_is_refused(tmp_path):
    # zh 写成 cn 在 Skybear 上是静默失效,保存时才报验证错误
    # (UPLOAD_RUNBOOK 第 3 条红线)。在这里就炸掉。
    with pytest.raises(SystemExit) as exc:
        load(tmp_path, highlights=[{"en": "a", "cn": "甲"}] * 6)
    assert "zh" in str(exc.value)


def test_a_region_box_with_its_bounds_swapped_is_refused(tmp_path):
    # 上下界写反了会让 in_region 对每一张图都返回 False,而那看起来和
    # 「这批候选全在别的大洲」一模一样 —— 正是要防的那种看不出来的错。
    with pytest.raises(SystemExit) as exc:
        load(tmp_path, commons_region_box=[44, 36, 105, 116])
    assert "commons_region_box" in str(exc.value)


def test_an_unknown_trip_type_name_is_refused(tmp_path):
    with pytest.raises(SystemExit) as exc:
        load(tmp_path, trip_types={"4:2": "MEAL"})
    assert "MEAL" in str(exc.value)


def test_a_missing_file_says_so_by_name(tmp_path):
    with pytest.raises(SystemExit) as exc:
        editorial.load("WBTEST", tmp_path)
    assert "work/WBTEST/editorial.json" in str(exc.value)


# --- 第二种错法:指向一个不存在的候选,解析引用时炸 ---------------------------

def _fixture(tmp_path: Path, blocks: dict, table: str = "commons.json") -> Path:
    """一个只有 itinerary + 一张候选表的最小产品目录。"""
    base = tmp_path / "WBTEST"
    base.mkdir(parents=True, exist_ok=True)
    (base / "itinerary.json").write_text(json.dumps(
        {"type_code": "WBTEST", "product_name": {"en": "T", "zh": "测"},
         "sections": [{"day": 3, "location": {"en": "Somewhere"},
                       "trip_items": []}]}), "utf-8")
    (base / table).write_text(json.dumps(blocks, ensure_ascii=False), "utf-8")
    (tmp_path / "pdf_subjects.json").write_text("{}", "utf-8")
    (tmp_path / "catalogue.json").write_text("{}", "utf-8")
    return tmp_path


GOOD_BLOCK = {"d03_x": {"day": 3, "subject": "X", "candidates": [
    {"n": 1, "url": "https://example/1", "path": "/tmp/1.jpg",
     "source": "commons", "credit": "someone", "license": "CC BY-SA 4.0"}]}}


def test_a_trip_pick_at_a_missing_index_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "WORK", _fixture(tmp_path, GOOD_BLOCK))
    with pytest.raises(SystemExit) as exc:
        compose.trip_pool("WBTEST", [("commons", ("d03_x", 9), "看过")])
    message = str(exc.value)
    assert "WBTEST" in message and "trip_picks" in message
    assert "d03_x#9" in message
    assert "fetch_commons" in message      # 怎么补


def test_a_trip_pick_at_a_missing_block_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "WORK", _fixture(tmp_path, GOOD_BLOCK))
    with pytest.raises(SystemExit) as exc:
        compose.trip_pool("WBTEST", [("commons", ("d03_typo", 1), "看过")])
    assert "d03_typo#1" in str(exc.value)


def test_a_trip_pick_that_resolves_keeps_credit_and_license(tmp_path, monkeypatch):
    # Commons 是唯一给全作者和许可证的图源(DESIGN 3.35),重构不许在路上丢掉。
    monkeypatch.setattr(compose, "WORK", _fixture(tmp_path, GOOD_BLOCK))
    pool = compose.trip_pool("WBTEST", [("commons", ("d03_x", 1), "看过")])
    assert [(p.credit, p.license) for p in pool] == [("someone", "CC BY-SA 4.0")]


def test_a_section_override_at_a_missing_index_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "WORK", _fixture(tmp_path, GOOD_BLOCK))
    with pytest.raises(SystemExit) as exc:
        compose.compose("WBTEST", "CHN", [],
                        {"d03": [("commons", ("d03_x", 9), "看过")]})
    message = str(exc.value)
    assert "section_overrides.d03" in message   # 哪个槽位
    assert "d03_x#9" in message                 # 指向了什么
    assert "WBTEST" in message                  # 哪个产品


def test_a_section_override_naming_a_missing_stock_block_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "WORK",
                        _fixture(tmp_path, GOOD_BLOCK, table="candidates.json"))
    with pytest.raises(SystemExit) as exc:
        compose.compose("WBTEST", "CHN", [],
                        {"d03": [("stock", ("d03_typo", 1), "看过")]})
    assert "d03_typo#1" in str(exc.value)
    assert "fetch_stock" in str(exc.value)


def test_a_section_override_naming_a_missing_catalogue_image_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "WORK", _fixture(tmp_path, GOOD_BLOCK))
    with pytest.raises(SystemExit) as exc:
        compose.compose("WBTEST", "CHN", [], {"d03": [("cat", "nope", "看过")]})
    assert "section_overrides.d03" in str(exc.value)
    assert "nope" in str(exc.value)
