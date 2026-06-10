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
    def _boom(snap_date, codes_by_value=None):
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
    monkeypatch.setattr(sector, "_fetch_sector_map", lambda d, c=None: {"005930": "전기전자"})
    assert sector.load_sector_map("2026-06-10") == {"005930": "전기전자"}
    saved = json.load(open(config.SECTOR_CACHE, encoding="utf-8"))
    assert saved["map"] == {"005930": "전기전자"} and saved["fetched"] == date.today().isoformat()
    # 재수집 실패(빈 dict) → 낡은 캐시 폴백
    _write_cache(stale_day, {"005930": "옛업종"})
    monkeypatch.setattr(sector, "_fetch_sector_map", lambda d, c=None: {})
    assert sector.load_sector_map("2026-06-10") == {"005930": "옛업종"}


def test_no_cache_no_fetch_returns_empty(tmp_repo, monkeypatch):
    monkeypatch.setattr(sector, "_fetch_sector_map", lambda d, c=None: {})
    assert sector.load_sector_map("2026-06-10") == {}


def test_fallback_chain_krx_kind_dart(tmp_repo, monkeypatch):
    """KRX → KIND → DART 순서. 앞 단계가 성공하면 뒷 단계를 호출하지 않는다."""
    boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("호출 금지"))  # noqa: E731
    # 전부 실패 → 빈 dict
    monkeypatch.setattr(sector, "_fetch_krx_sector_map", lambda d: {})
    monkeypatch.setattr(sector, "_fetch_kind_sector_map", lambda: {})
    monkeypatch.setattr(sector, "_fetch_dart_sector_map", lambda codes: {})
    assert sector._fetch_sector_map("2026-06-10", ["005930"]) == {}
    # KRX·KIND 실패 → DART 사용
    monkeypatch.setattr(sector, "_fetch_dart_sector_map", lambda codes: {"005930": "전자부품·통신장비"})
    assert sector._fetch_sector_map("2026-06-10", ["005930"]) == {"005930": "전자부품·통신장비"}
    # KIND 성공 → DART 미호출
    monkeypatch.setattr(sector, "_fetch_kind_sector_map", lambda: {"005930": "통신 및 방송 장비 제조업"})
    monkeypatch.setattr(sector, "_fetch_dart_sector_map", boom)
    assert sector._fetch_sector_map("2026-06-10", ["005930"]) == {"005930": "통신 및 방송 장비 제조업"}
    # KRX 성공 → KIND·DART 미호출
    monkeypatch.setattr(sector, "_fetch_krx_sector_map", lambda d: {"005930": "전기전자"})
    monkeypatch.setattr(sector, "_fetch_kind_sector_map", boom)
    assert sector._fetch_sector_map("2026-06-10", ["005930"]) == {"005930": "전기전자"}


def test_dart_sector_map(tmp_repo, monkeypatch):
    """기업개황 induty_code 앞 2자리 → KSIC 중분류명. 중단 status면 즉시 종료."""
    monkeypatch.setenv("DART_API_KEY", "k")
    monkeypatch.setattr(sector, "load_dart_corp_map",
                        lambda key: {"005930": "00126380", "005380": "00164742"})
    responses = {
        "00126380": {"status": "000", "induty_code": "264"},   # 26 → 전자부품·통신장비
        "00164742": {"status": "000", "induty_code": "30121"},  # 30 → 자동차
    }
    def fake_download(url, **kw):
        corp = url.split("corp_code=")[1]
        return json.dumps(responses[corp]).encode()
    monkeypatch.setattr(sector, "_download", fake_download)
    out = sector._fetch_dart_sector_map(["005930", "005380", "999999"])  # 매핑 없는 코드는 건너뜀
    assert out == {"005930": "전자부품·통신장비", "005380": "자동차"}
    # 사용량 초과(020) → 수집 중단(이후 종목 미조회)
    calls = []
    def fake_abort(url, **kw):
        calls.append(url)
        return json.dumps({"status": "020", "message": "limit"}).encode()
    monkeypatch.setattr(sector, "_download", fake_abort)
    assert sector._fetch_dart_sector_map(["005930", "005380"]) == {}
    assert len(calls) == 1


def test_dart_sector_map_no_key(tmp_repo, monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.setattr(sector, "load_dart_corp_map",
                        lambda key: (_ for _ in ()).throw(AssertionError("호출 금지")))
    assert sector._fetch_dart_sector_map(["005930"]) == {}


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
