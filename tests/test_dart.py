"""DART 「대량보유 상황보고」 — corpCode 매핑 캐시, 최신 보고 선택, 키·오류 처리. 전부 오프라인."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, timedelta

from nps_tracker import config
from nps_tracker.sources import dart

CORPCODE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name><stock_code>005930</stock_code><modify_date>20260101</modify_date></list>
  <list><corp_code>00164742</corp_code><corp_name>SK하이닉스</corp_name><stock_code>000660</stock_code><modify_date>20260101</modify_date></list>
  <list><corp_code>00999999</corp_code><corp_name>비상장사</corp_name><stock_code> </stock_code><modify_date>20260101</modify_date></list>
</result>"""


def _zip_bytes(xml: str = CORPCODE_XML) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", xml)
    return buf.getvalue()


def _majorstock(items) -> bytes:
    return json.dumps({"status": "000", "message": "정상", "list": items},
                      ensure_ascii=False).encode("utf-8")


def _holding(code: str, ownership: float = 7.0) -> dict:
    return {"stock_code": code, "stock_name": f"종목{code}", "shares": 100, "ownership_pct": ownership}


# ---------- corpCode 매핑 ----------
def test_corp_map_parse_filters_unlisted(tmp_repo, monkeypatch):
    calls = []
    monkeypatch.setattr(dart, "_download", lambda url, **kw: calls.append(url) or _zip_bytes())
    m = dart.load_dart_corp_map("KEY")
    assert m == {"005930": "00126380", "000660": "00164742"}  # 비상장(공백 stock_code) 제외
    assert len(calls) == 1
    # 두 번째 호출은 신선한 캐시 사용 → 다운로드 없음
    assert dart.load_dart_corp_map("KEY") == m
    assert len(calls) == 1


def test_corp_map_stale_cache_refetch_and_fallback(tmp_repo, monkeypatch):
    old = (date.today() - timedelta(days=config.DART_CORP_CACHE_MAX_AGE_DAYS + 5)).isoformat()
    from nps_tracker.io_utils import _write_json
    _write_json(config.DART_CORP_CACHE, {"fetched": old, "map": {"005930": "00126380"}})
    # 낡은 캐시 → 재수집 시도, 성공하면 새 맵으로 교체
    monkeypatch.setattr(dart, "_download", lambda url, **kw: _zip_bytes())
    assert "000660" in dart.load_dart_corp_map("KEY")
    # 재수집 실패 시 낡은 캐시로 폴백
    _write_json(config.DART_CORP_CACHE, {"fetched": old, "map": {"005930": "00126380"}})
    def boom(url, **kw):
        raise OSError("network down")
    monkeypatch.setattr(dart, "_download", boom)
    assert dart.load_dart_corp_map("KEY") == {"005930": "00126380"}


# ---------- 보고 선택 ----------
def test_latest_nps_report_wins():
    items = [
        {"repror": "국민연금공단", "stkqy": "1,000", "rcept_dt": "2026-01-02", "rcept_no": "20260102000001"},
        {"repror": "국민연금공단", "stkqy": "2,000", "rcept_dt": "20260413", "rcept_no": "20260413000009"},
        {"repror": "다른기관", "stkqy": "9,999", "rcept_dt": "2026-05-01", "rcept_no": "20260501000001"},
    ]
    assert dart._latest_nps_shares(items) == 2000  # 최신 국민연금 보고, 쉼표·날짜 포맷 흡수
    assert dart._latest_nps_shares([]) is None
    assert dart._latest_nps_shares([{"repror": "다른기관", "stkqy": "1"}]) is None


# ---------- fetch_dart_nps_shares ----------
def test_missing_key_skips_without_network(tmp_repo, monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    def fail(url, **kw):
        raise AssertionError("네트워크 호출 금지")
    monkeypatch.setattr(dart, "_download", fail)
    assert dart.fetch_dart_nps_shares([_holding("005930")]) == {}


def test_fetch_shares_happy_and_candidate_filter(tmp_repo, monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "KEY")
    queried = []
    def fake_download(url, **kw):
        if "corpCode" in url:
            return _zip_bytes()
        queried.append(url)
        if "00126380" in url:  # 삼성전자: 두 보고 중 최신이 이김
            return _majorstock([
                {"repror": "국민연금공단", "stkqy": "1,000", "rcept_dt": "2026-01-02", "rcept_no": "1"},
                {"repror": "국민연금공단", "stkqy": "2,000", "rcept_dt": "2026-04-13", "rcept_no": "2"},
            ])
        return json.dumps({"status": "013", "message": "조회된 데이타가 없습니다."}).encode()  # SK하이닉스
    monkeypatch.setattr(dart, "_download", fake_download)
    holdings = [
        _holding("005930", 7.0),
        _holding("000660", 5.5),
        _holding("035420", 3.0),   # 후보 미달(<4.5%) → 조회 자체를 안 함
        _holding("999999", 6.0),   # corp 매핑 없음 → 건너뜀
    ]
    out = dart.fetch_dart_nps_shares(holdings)
    assert out == {"005930": 2000}          # 013(데이터 없음)은 해당 종목만 생략
    assert len(queried) == 2                # 후보 2종목만 majorstock 조회


def test_abort_status_stops_remaining_calls(tmp_repo, monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "KEY")
    queried = []
    def fake_download(url, **kw):
        if "corpCode" in url:
            return _zip_bytes()
        queried.append(url)
        return json.dumps({"status": "020", "message": "요청 제한을 초과하였습니다."}).encode()
    monkeypatch.setattr(dart, "_download", fake_download)
    out = dart.fetch_dart_nps_shares([_holding("005930"), _holding("000660")])
    assert out == {}
    assert len(queried) == 1  # 첫 응답에서 한도 초과 → 이후 종목 호출 중단


def test_invalid_key_corpcode_not_zip(tmp_repo, monkeypatch):
    """키 오류 시 corpCode가 zip이 아닌 XML 에러로 와도 안전하게 빈 dict."""
    monkeypatch.setenv("DART_API_KEY", "BAD")
    monkeypatch.setattr(dart, "_download",
                        lambda url, **kw: "<result><status>010</status></result>".encode())
    assert dart.fetch_dart_nps_shares([_holding("005930")]) == {}
