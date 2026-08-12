from decimal import Decimal

from lib.pricing import (
    DEFAULT_CHILD_NO_BED_DIFF,
    DEFAULT_CHILD_WITH_BED_DIFF,
    DEFAULT_SINGLE_SUPPLEMENT,
    ESTIMATED_COST_DEFAULTS,
    derive_tour_fare,
)


def test_default_formula_with_wbmxmn_2199():
    """v1 默认规则 (Planner 输入 twin_price=2199):
       TWN = TRP = ChdHfTwn = 2199;  ChdWEbed = 2159;  ChdWOBed = 2099;  SGL = 2599."""
    fare = derive_tour_fare(Decimal("2199"))
    assert fare.twin == Decimal("2199")
    assert fare.triple == Decimal("2199")
    assert fare.child_half_twin == Decimal("2199")
    assert fare.child_with_bed == Decimal("2159")
    assert fare.child_no_bed == Decimal("2099")
    assert fare.single == Decimal("2599")
    assert fare.infant == Decimal("0")


def test_planner_overrides():
    fare = derive_tour_fare(
        Decimal("3000"),
        single_supplement=Decimal("500"),
        child_with_bed_diff=Decimal("0"),
        child_no_bed_diff=Decimal("-200"),
        infant_price=Decimal("400"),
    )
    assert fare.twin == Decimal("3000")
    assert fare.single == Decimal("3500")
    assert fare.child_with_bed == Decimal("3000")
    assert fare.child_no_bed == Decimal("2800")
    assert fare.infant == Decimal("400")


def test_default_constants():
    assert DEFAULT_SINGLE_SUPPLEMENT == Decimal("400")
    assert DEFAULT_CHILD_WITH_BED_DIFF == Decimal("-40")
    assert DEFAULT_CHILD_NO_BED_DIFF == Decimal("-100")


def test_estimated_cost_has_9_required_fields():
    """SPEC §9 关键发现 #3：Edit Package 页 Estimated Cost 区 9 字段全必填."""
    assert len(ESTIMATED_COST_DEFAULTS) == 9
    assert ESTIMATED_COST_DEFAULTS["Sales Commission"] == Decimal("30")
    assert all(
        v == Decimal("0")
        for k, v in ESTIMATED_COST_DEFAULTS.items()
        if k != "Sales Commission"
    )
