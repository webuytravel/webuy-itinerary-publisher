from dataclasses import dataclass
from typing import Optional

from .config import Settings
from .db import ro_connection


@dataclass(frozen=True)
class TourTypeRef:
    id: int
    type_code: str
    type_name: str
    pax_type: int
    travel_days: Optional[int]
    area_id: int


@dataclass(frozen=True)
class TourRef:
    id: int
    tour_code: str


@dataclass(frozen=True)
class TravelRef:
    id: int
    product_name: str
    travel_status: int   # 0 = Not for sale (草稿), 1 = publish for sale


@dataclass(frozen=True)
class ExistenceReport:
    tour_type: Optional[TourTypeRef]
    tour: Optional[TourRef]
    travel: Optional[TravelRef]


def check(settings: Settings, type_code: str, tour_code: str) -> ExistenceReport:
    """3 个 SELECT — 决定 Step 1 / Step 2 / Step 3 各自是 NEW 还是 REUSE.

    **For developers only** — Cowork plugin colleagues do NOT call this.
    The runtime SKILL.md uses Skybear's Package List search UI to look up
    tour_id after Modal Save, so colleagues don't need to configure
    SKYBEAR_RO_MYSQL_* env vars.

    Phase 0 关键发现 (#5)：即使 wt_tour 已存在，wt_travel_tour 关联可能没建。
    本 check 只回答 "wt_travel 行存在与否"，关联是 Phase 2 自动化的职责。
    """
    with ro_connection(settings) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, type_code, type_name, pax_type, travel_days, area_id "
            "FROM wt_tour_type WHERE type_code = %s AND type_status = 0 LIMIT 1",
            (type_code,),
        )
        tt_row = cur.fetchone()
        tour_type = TourTypeRef(**tt_row) if tt_row else None

        cur.execute(
            "SELECT id, tour_code FROM wt_tour "
            "WHERE tour_code = %s AND deleted_status = 0 LIMIT 1",
            (tour_code,),
        )
        t_row = cur.fetchone()
        tour = TourRef(**t_row) if t_row else None

        travel: Optional[TravelRef] = None
        if tour_type:
            cur.execute(
                "SELECT id, product_name, travel_status FROM wt_travel "
                "WHERE tour_type_id = %s AND delete_status = 0 "
                "ORDER BY id DESC LIMIT 1",
                (tour_type.id,),
            )
            tv_row = cur.fetchone()
            travel = TravelRef(**tv_row) if tv_row else None

    return ExistenceReport(tour_type=tour_type, tour=tour, travel=travel)
