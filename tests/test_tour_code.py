from datetime import date

import pytest

from lib.tour_code import derive_tour_code


def test_uat_wbmxmn_2026_dec_mf():
    """SPEC §3 与 UAT 实测样例:  (2026-12-10, WBMXMN, MF) → 12WBMXMN10/26MF."""
    parts = derive_tour_code(date(2026, 12, 10), "WBMXMN", "MF")
    assert parts.full == "12WBMXMN10/26MF"
    assert parts.mm == "12"
    assert parts.type_code == "WBMXMN"
    assert parts.suffix == "10/26MF"


def test_existing_uat_wbmxmn_march_2026():
    """UAT 真实存在的 6 个 WBMXMN tour code 之一: 03WBMXMN06/26MF."""
    parts = derive_tour_code(date(2026, 3, 6), "WBMXMN", "MF")
    assert parts.full == "03WBMXMN06/26MF"


def test_century_rollover():
    """Year 2000 → "00", year 2099 → "99"."""
    assert derive_tour_code(date(2000, 1, 1), "X", "Y").full == "01X01/00Y"
    assert derive_tour_code(date(2099, 12, 31), "X", "Y").full == "12X31/99Y"


def test_missing_type_code_or_airline_raises():
    with pytest.raises(ValueError):
        derive_tour_code(date(2026, 1, 1), "", "MF")
    with pytest.raises(ValueError):
        derive_tour_code(date(2026, 1, 1), "WBMXMN", "")
