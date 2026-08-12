from dataclasses import dataclass
from decimal import Decimal


# v1 默认价格规则（Planner 可在聊天里逐项覆盖）：
#   TWNfare = TRPFare = ChdHfTwn = twin_price
#   ChdWEbed = TWNfare - 40
#   ChdWOBed = TWNfare - 100
#   SGLfare  = TWNfare + 400  （SGLfare 是 Single Room 总价，不是 supplement 增量）
DEFAULT_SINGLE_SUPPLEMENT = Decimal("400")
DEFAULT_CHILD_WITH_BED_DIFF = Decimal("-40")
DEFAULT_CHILD_NO_BED_DIFF = Decimal("-100")


@dataclass(frozen=True)
class TourFare:
    """Skybear Edit Package 页 Tour Fare 区 7 档 sellPrice，对应 wt_tour_price (price_type=1)."""
    twin: Decimal       # TWNfare
    triple: Decimal     # TRPFare
    child_half_twin: Decimal  # ChdHfTwn
    child_with_bed: Decimal   # ChdWEbed
    child_no_bed: Decimal     # ChdWOBed
    single: Decimal     # SGLfare (单房总价 = twin + supplement)
    infant: Decimal     # InfFare


def derive_tour_fare(
    twin_price: Decimal,
    *,
    single_supplement: Decimal = DEFAULT_SINGLE_SUPPLEMENT,
    child_with_bed_diff: Decimal = DEFAULT_CHILD_WITH_BED_DIFF,
    child_no_bed_diff: Decimal = DEFAULT_CHILD_NO_BED_DIFF,
    infant_price: Decimal = Decimal("0"),
) -> TourFare:
    twin = Decimal(twin_price)
    return TourFare(
        twin=twin,
        triple=twin,
        child_half_twin=twin,
        child_with_bed=twin + Decimal(child_with_bed_diff),
        child_no_bed=twin + Decimal(child_no_bed_diff),
        single=twin + Decimal(single_supplement),
        infant=Decimal(infant_price),
    )


# Edit Package 页 Estimated Cost 区 9 个必填字段。v1 全填 0
# (Sales Commission 默认 30 留着即可，但 form_input 显式写 30 更稳)
ESTIMATED_COST_DEFAULTS: dict[str, Decimal] = {
    "Air Ticket": Decimal("0"),
    "Airport Taxes": Decimal("0"),
    "Land Tour Cost": Decimal("0"),
    "Tour Leader Cost": Decimal("0"),
    "Celebrity Cost": Decimal("0"),
    "Referral Cost": Decimal("0"),
    "Sales Commission": Decimal("30"),
    "Back Office Commission": Decimal("0"),
    "Celebrity Commission": Decimal("0"),
}
