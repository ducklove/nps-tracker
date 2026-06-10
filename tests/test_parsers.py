"""각 소스 파서가 문서화된 포맷(fixture)을 정확히 파싱하는지 — 네트워크는 monkeypatch."""
from __future__ import annotations

import json

import pytest

from nps_tracker.http import _decode_csv
from nps_tracker.sources import datago, fnguide, kosis, sheet
from nps_tracker.sources.datago import _parse_fund_period
from nps_tracker.sources.sheet import _parse_sheet_period
from tests.conftest import read_fixture


# ---------- 디코딩 ----------
def test_decode_csv_cp949():
    assert _decode_csv("종목명,평가액".encode("cp949")) == "종목명,평가액"


def test_decode_csv_utf8_sig_strips_bom():
    assert _decode_csv("번호,종목명".encode("utf-8-sig")) == "번호,종목명"


# ---------- 공공데이터 보유내역 ----------
@pytest.fixture
def no_discover(monkeypatch):
    monkeypatch.setenv("NPS_PUBLIC_DATA_DISCOVER", "0")


def test_fetch_public_holdings(monkeypatch, no_discover):
    calls = []

    def fake_download(url, referer=None, **kw):
        calls.append(url)
        return read_fixture("public_holdings.csv")

    monkeypatch.setattr(datago, "_download", fake_download)
    rows, src_date = datago.fetch_public_holdings()

    assert src_date == "2024-12-31"  # discover 생략 → fallback 날짜
    assert len(calls) == 1  # discover 없이 CSV 1회만
    assert [r["name"] for r in rows] == ["삼성전자", "SK하이닉스", "한국전력", "별칭없는상사"]
    samsung = rows[0]
    assert samsung["source_market_value"] == 399_300 * 100_000_000  # 억원 → 원, 천단위 콤마 처리
    assert samsung["ownership_pct"] == 7.26
    assert samsung["rank"] == 1
    # 합계 행(번호 없음)·종목명 없는 행은 제외
    assert all(r["name"] for r in rows) and all(r["rank"] for r in rows)


def test_get_public_holdings_resolves_and_threshold(monkeypatch, no_discover, tmp_repo):
    """매핑은 되지만 MIN_RESOLVED_HOLDINGS(100) 미만 → None(seed 폴백 신호)."""
    monkeypatch.setattr(datago, "_download", lambda *a, **k: read_fixture("public_holdings.csv"))
    assert datago.get_public_holdings() is None  # 4종목 < 100


# ---------- FnGuide ----------
def test_fetch_fnguide_holdings(monkeypatch):
    monkeypatch.setattr(fnguide, "_download", lambda *a, **k: read_fixture("fnguide.html"))
    rows = fnguide.fetch_fnguide_holdings()
    # rank 숫자 + 수량>0 + td 7개 이상 행만 남는다 (합계행·수량 0·짧은 행 제외)
    assert rows == [
        {"name": "삼성전자", "shares": 458_637_667},
        {"name": "SK하이닉스", "shares": 46_392_067},
    ]


def test_fetch_fnguide_shares_maps_codes(monkeypatch):
    monkeypatch.setattr(fnguide, "_download", lambda *a, **k: read_fixture("fnguide.html"))
    resolver = ({"삼성전자": "005930", "SK하이닉스": "000660"}, {}, [])
    assert fnguide.fetch_fnguide_shares(resolver) == {"005930": 458_637_667, "000660": 46_392_067}


def test_fetch_fnguide_shares_failure_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(fnguide, "_download", boom)
    assert fnguide.fetch_fnguide_shares(({}, {}, [])) == {}


# ---------- KOSIS ----------
def test_fetch_kosis_fund_monthly(monkeypatch):
    monkeypatch.setenv("KOSIS_API_KEY", "test-key")
    monkeypatch.setattr(kosis, "_download", lambda *a, **k: read_fixture("kosis.json"))
    series = kosis.fetch_kosis_fund_monthly()

    assert [s["period"] for s in series] == ["2024-01", "2024-12"]  # C2=01 연간행 제외
    jan = series[0]
    WON = 1_000_000  # 백만원 → 원
    assert jan["total"] == 1_000_000 * WON
    assert jan["domestic_stock"] == (300_000 - 180_000) * WON  # A010-A014
    assert jan["foreign_stock"] == 180_000 * WON
    assert jan["domestic_bond"] == (400_000 - 50_000) * WON  # A005-A009
    assert jan["foreign_bond"] == 50_000 * WON
    assert jan["alternative"] == 200_000 * WON
    assert jan["short_term"] == 30_000 * WON
    assert jan["welfare"] == (10_000 + 5_000) * WON
    assert jan["etc"] == (3_000 + 2_000) * WON
    assert series[1]["total"] == jan["total"] * 2  # 12월 = 1월의 2배 fixture


def test_fetch_kosis_without_key_skips(monkeypatch):
    monkeypatch.delenv("KOSIS_API_KEY", raising=False)
    monkeypatch.setattr(kosis, "_download", lambda *a, **k: pytest.fail("네트워크 호출되면 안 됨"))
    assert kosis.fetch_kosis_fund_monthly() is None


# ---------- Google Sheet ----------
def test_fetch_sheet_fund(monkeypatch):
    monkeypatch.setattr(sheet, "_download", lambda *a, **k: read_fixture("sheet.csv"))
    out = sheet.fetch_sheet_fund()

    # 잡음 행 건너뛰고 기준월 헤더 발견, 결측 행(2026.03)은 제외
    assert [r["period"] for r in out] == ["2026-01", "2026-02"]
    jan = out[0]
    WON = 100_000_000  # 억원 → 원
    assert jan["source"] == "sheet"
    assert jan["domestic_bond"] == 3_300_000 * WON
    assert jan["foreign_bond"] == 1_000_000 * WON
    assert jan["domestic_stock"] == 1_500_000 * WON
    assert jan["foreign_stock"] == 4_800_000 * WON
    assert jan["alternative"] == 2_000_000 * WON
    assert jan["short_term"] == 50_000 * WON


def test_fetch_sheet_fund_private_html(monkeypatch):
    monkeypatch.setattr(sheet, "_download", lambda *a, **k: b"<HTML><body>sign in</body></HTML>")
    assert sheet.fetch_sheet_fund() is None


def test_parse_sheet_period():
    assert _parse_sheet_period("2026.01") == "2026-01"
    assert _parse_sheet_period("2026-2") == "2026-02"
    assert _parse_sheet_period("2026/12") == "2026-12"
    assert _parse_sheet_period("비고") is None


# ---------- 기금 포트폴리오 현황(data.go.kr) ----------
def test_parse_fund_period():
    assert _parse_fund_period("2026년 2월(십억 원)") == "2026-02"
    assert _parse_fund_period("2025년(십억 원)") == "2025-12"  # 연도만 = 연말
    assert _parse_fund_period("현황(말잔_십억원)") is None


def test_fetch_fund_portfolio(monkeypatch):
    monkeypatch.setenv("NPS_PUBLIC_DATA_DISCOVER", "0")
    monkeypatch.setattr(datago, "_download", lambda *a, **k: read_fixture("fund_portfolio.csv"))
    fp = datago.fetch_fund_portfolio()

    assert fp["unit"] == "won"
    assert fp["asOf"] == "2026-02"
    periods = [s["period"] for s in fp["series"]]
    assert periods == ["2024-12", "2025-12", "2026-02"]  # 기간 아닌 '현황' 컬럼 제외
    last = fp["series"][-1]
    B = 1_000_000_000  # 십억원 → 원
    assert last["total"] == 1_350_000 * B
    assert last["domestic_stock"] == 152_000 * B
    assert last["welfare"] == 220 * B
    assert last["etc"] == 120 * B


def test_kosis_fixture_is_valid_json():
    assert isinstance(json.loads(read_fixture("kosis.json")), list)
