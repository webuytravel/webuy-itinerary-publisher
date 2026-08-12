"""集成测试：连真 UAT MySQL 验证 WBMXMN existence check 返回正确数据.

跳过条件：未配置 .env (无 SKYBEAR_RO_MYSQL_PASSWORD)."""
import os

import pytest

from lib.config import load_settings
from lib.existence_check import check


@pytest.fixture(scope="module")
def settings():
    if not os.getenv("SKYBEAR_RO_MYSQL_PASSWORD") and not _dotenv_has_password():
        pytest.skip("SKYBEAR_RO_MYSQL_PASSWORD not set; skipping integration test")
    return load_settings()


def _dotenv_has_password() -> bool:
    from pathlib import Path
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return False
    text = env_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("SKYBEAR_RO_MYSQL_PASSWORD=") and line.split("=", 1)[1].strip():
            return True
    return False


def test_wbmxmn_exists_with_known_id(settings):
    """SPEC §3: WBMXMN 在 UAT 已存在 id=595, pax_type=1, travel_days=7, area_id=337."""
    report = check(settings, type_code="WBMXMN", tour_code="12WBMXMN10/26MF")
    assert report.tour_type is not None, "WBMXMN 应该已存在"
    assert report.tour_type.id == 595
    assert report.tour_type.type_code == "WBMXMN"
    assert report.tour_type.pax_type == 1
    assert report.tour_type.travel_days == 7
    assert report.tour_type.area_id == 337


def test_phase_3_tour_now_exists(settings):
    """Phase 3 dry-run 在 UAT 创建了 12WBMXMN10/26MF (id=11571)."""
    report = check(settings, type_code="WBMXMN", tour_code="12WBMXMN10/26MF")
    assert report.tour is not None
    assert report.tour.id == 11571
    assert report.tour.tour_code == "12WBMXMN10/26MF"


def test_truly_nonexistent_tour_code_returns_none(settings):
    """Sanity: a truly random tour code returns None."""
    report = check(settings, type_code="WBMXMN", tour_code="99WBMXMN99/99ZZ")
    assert report.tour is None


def test_wbmxmn_travel_exists_as_draft(settings):
    """SPEC §9 发现 #11: WBMXMN 有 wt_travel id=149 草稿态."""
    report = check(settings, type_code="WBMXMN", tour_code="anything")
    assert report.travel is not None
    assert report.travel.id == 149
    assert report.travel.travel_status == 0  # Not for sale = 草稿


def test_unknown_type_code_returns_none(settings):
    report = check(settings, type_code="ZZZZZZ_NOT_EXIST", tour_code="anything")
    assert report.tour_type is None
    assert report.travel is None
