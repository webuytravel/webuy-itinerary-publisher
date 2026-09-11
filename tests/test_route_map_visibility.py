"""路线图槽空着时，两条报告路径都必须自己响。

这一槽原来对所有报告路径都是隐形的：`bin/review_page.py` 的槽循环遇到空槽
直接 `continue`，整节不渲染，于是「没有路线图」和「本来就不该有路线图」在
签字页上长得一模一样；`bin/compose.py` 的摘要行只把它记成 `route=0`，夹在
sections / carousel / thumb / gaps 一串数字中间。两边都不响，所以一页
《Special Terms and Conditions》被当成 `wt_travel.routeMapUrl` 传上去之后，
没有任何一处会说少了什么。

判断标准是 docs/DESIGN.md 6.9：当一个失败的后果是「页面上少了东西」而不是
「程序不能继续」时，它必须响。
"""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lib.image_plan import ImagePlan, Placement

BIN = Path(__file__).resolve().parent.parent / "bin"


def _module(name):
    """bin/ 不是包，按文件路径加载。"""
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compose = _module("compose")
review_page = _module("review_page")


# --- compose 的摘要行 --------------------------------------------------------

def _plan(*placements):
    return ImagePlan(type_code="WBTEST", region="CHN", placements=list(placements))


def _route_map():
    return Placement(slot="route_map", position=0, origin="pdf",
                     subject="itinerary route map", source_ref="p2 #1",
                     src_path="work/WBTEST/pdf/p2_1.png")


def test_no_route_map_gets_its_own_line_not_just_route_equals_zero():
    notice = compose.route_map_notice(_plan(
        Placement(slot="section", position=1, origin="web", subject="Ordos",
                  source_ref="ref", src_path="work/WBTEST/cand/d01.jpg")))
    assert notice is not None
    # 抬头要和 `NO SECTION PHOTO` 一样能被人一眼扫到，`route=0` 那个数字不算。
    assert "NO ROUTE MAP" in notice


def test_a_product_that_has_a_route_map_stays_quiet():
    assert compose.route_map_notice(_plan(_route_map())) is None


# --- 审核页 ------------------------------------------------------------------

def _photo(path: Path) -> Path:
    rng = np.random.default_rng(0)
    Image.fromarray(rng.integers(0, 255, (90, 120, 3), dtype=np.uint8),
                    "RGB").save(path)
    return path


@pytest.fixture
def product(tmp_path, monkeypatch):
    """在 tmp 里搭一个最小产品，返回一个写 plan.json 的函数。"""
    work = tmp_path / "work"
    code = "WBTEST"
    (work / code).mkdir(parents=True)
    monkeypatch.setattr(review_page, "WORK", work)
    (work / code / "itinerary.json").write_text(json.dumps({
        "product_name": {"en": "Test Tour", "zh": "测试团"},
        "travel_days": 2,
        "highlights": ["h1"],
        "sections": [
            {"day": 1, "title": {"en": "Arrival"},
             "trip_items": [{"title": {"en": "City Walk"}}]},
            {"day": 2, "title": {"en": "Homeward Bound"}, "trip_items": []},
        ],
    }, ensure_ascii=False), "utf-8")

    def write_plan(placements):
        (work / code / "plan.json").write_text(
            json.dumps({"placements": placements, "gaps": []},
                       ensure_ascii=False), "utf-8")
        return code

    write_plan.work = work
    return write_plan


def _section_photo(work, code):
    return {"slot": "section", "position": 1, "origin": "web",
            "subject": "City Walk", "source_ref": "ref",
            "src_path": str(_photo(work / code / "d01.jpg"))}


def test_an_empty_route_map_slot_is_stated_not_omitted(product):
    # 有别的槽有图，所以页面本身是正常渲染的——原来的 `continue` 就是在这种
    # 情况下让路线图那一节整个消失，页面看上去完好无损。
    code = product([_section_photo(product.work, "WBTEST")])
    html = review_page.product_block(code)
    assert "路线图" in html
    assert "没有路线图" in html
    assert "⚠" in html


def test_a_product_with_a_route_map_shows_it_and_raises_no_notice(product):
    work = product.work
    code = product([
        _section_photo(work, "WBTEST"),
        {"slot": "route_map", "position": 0, "origin": "pdf",
         "subject": "itinerary route map", "source_ref": "p2 #1",
         "src_path": str(_photo(work / "WBTEST" / "route.jpg"))},
    ])
    html = review_page.product_block(code)
    assert "itinerary route map" in html
    assert "没有路线图" not in html
