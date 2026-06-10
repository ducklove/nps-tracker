"""sector(F-7) — 업종 캐시 수명주기와 섹터 집계 산식. 전부 오프라인(pykrx 미호출)."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from nps_tracker import config
from nps_tracker.sources import sector


@pytest.fixture
def no_fetch(monkeypatch):
    """_fetch_sector_map 호출을 금지(호출되면 실패) — 캐시 적중 경로 검증용."""
    def _boom(snap_date):
        raise AssertionError("네트워크 수집이 호출되면 안 됨")
    monkeypatch.setattr(sector, "_fetch_sector_map", _boom)


def _write_cache(fetched: str, cmap: dict):
    with open(config.SECTOR_CACHE, "w", encoding="utf-8") as f:
        json.dump({"fetched": fetched, "map": cmap}, f, ensure_ascii=False)


def test_fresh_cache_skips_fetch(tmp_repo, no_fetch):
    _write_cache(date.today().isoformat(), {"005930": "전기전자"})
    assert sector.load_sector_map("2026-06-10") == {"005930": "전기전자"}


def test_stale_cache_refetch_and_fallback(tmp_repo, monkeypatch):
    stale_day = (date.today() - timedelta(days=config.SECTOR_CACHE_MAX_AGE_DAYS + 1)).isoformat()
    _write_cache(stale_day, {"005930": "옛업종"})
    # 재수집 성공 → 새 맵으로 교체 + 캐시 갱신
    monkeypatch.setattr(sector, "_fetch_sector_map", lambda d: {"005930": "전기전자"})
    assert sector.load_sector_map("2026-06-10") == {"005930": "전기전자"}
    saved = json.load(open(config.SECTOR_CACHE, encoding="utf-8"))
    assert saved["map"] == {"005930": "전기전자"} and saved["fetched"] == date.today().isoformat()
    # 재수집 실패(빈 dict) → 낡은 캐시 폴백
    _write_cache(stale_day, {"005930": "옛업종"})
    monkeypatch.setattr(sector, "_fetch_sector_map", lambda d: {})
    assert sector.load_sector_map("2026-06-10") == {"005930": "옛업종"}


def test_no_cache_no_fetch_returns_empty(tmp_repo, monkeypatch):
    monkeypatch.setattr(sector, "_fetch_sector_map", lambda d: {})
    assert sector.load_sector_map("2026-06-10") == {}


def test_kind_fallback_when_krx_empty(tmp_repo, monkeypatch):
    """KRX 업종분류가 비면(로그인 미설정) KIND 산업분류로 폴백한다."""
    monkeypatch.setattr(sector, "_fetch_krx_sector_map", lambda d: {})
    monkeypatch.setattr(sector, "_fetch_kind_sector_map", lambda: {"005930": "통신 및 방송 장비 제조업"})
    assert sector._fetch_sector_map("2026-06-10") == {"005930": "통신 및 방송 장비 제조업"}
    # KRX가 성공하면 KIND를 호출하지 않는다
    monkeypatch.setattr(sector, "_fetch_krx_sector_map", lambda d: {"005930": "전기전자"})
    monkeypatch.setattr(sector, "_fetch_kind_sector_map",
                        lambda: (_ for _ in ()).throw(AssertionError("KIND 호출 금지")))
    assert sector._fetch_sector_map("2026-06-10") == {"005930": "전기전자"}


def test_parse_kind_corplist():
    html = """
    <table><thead><tr><th>회사명</th><th>종목코드</th><th>업종</th><th>주요제품</th></tr></thead>
    <tbody>
    <tr><td><a href="#">삼성전자</a></td><td>005930</td><td>통신 및 방송 장비 제조업</td><td>스마트폰</td></tr>
    <tr><td>비상장</td><td>ABCDEF</td><td>업종</td><td>-</td></tr>
    <tr><td>빈업종</td><td>123456</td><td></td><td>-</td></tr>
    </tbody></table>
    """
    assert sector._parse_kind_corplist(html) == {"005930": "통신 및 방송 장비 제조업"}


def test_sector_for_preferred_fallback():
    smap = {"005930": "전기전자"}
    assert sector.sector_for("005930", smap) == "전기전자"
    assert sector.sector_for("005935", smap) == "전기전자"  # 삼성전자우 → 보통주 업종
    assert sector.sector_for("000660", smap) is None


def _ev(code, sector_name, mv, chg):
    h = {"stock_code": code, "stock_name": code, "market_value": mv, "change_pct": chg}
    if sector_name:
        h["sector"] = sector_name
    return h


def test_aggregate_sectors_math(tmp_repo):
    rows = [
        _ev("A", "전기전자", 110, 10.0),   # prev 100
        _ev("B", "전기전자", 95, -5.0),    # prev 100
        _ev("C", "서비스업", 100, None),   # 등락 미상 — 비중에만 기여
        _ev("D", None, 100, 0.0),          # 미분류 — prev 100
    ]
    out = sector.aggregate_sectors(rows)
    by = {s["name"]: s for s in out}
    assert set(by) == {"전기전자", "서비스업", config.SECTOR_UNMAPPED_LABEL}
    elec = by["전기전자"]
    assert elec["value"] == 205 and elec["count"] == 2
    assert elec["weightPct"] == round(205 / 405 * 100, 2)
    assert elec["changePct"] == round((205 - 200) / 200 * 100, 2)   # +2.5%
    assert elec["contribPct"] == round(5 / 300 * 100, 3)            # 전일합 300(미상 제외) 대비
    svc = by["서비스업"]
    assert svc["changePct"] is None and svc["contribPct"] is None and svc["weightPct"] > 0
    # 정렬: 평가액 내림차순
    assert [s["name"] for s in out] == sorted([s["name"] for s in out],
                                              key=lambda n: -by[n]["value"])


def test_aggregate_sectors_empty_without_mapping(tmp_repo):
    rows = [_ev("A", None, 100, 1.0), _ev("B", None, 50, -1.0)]
    assert sector.aggregate_sectors(rows) == []
