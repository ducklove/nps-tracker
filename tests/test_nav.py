"""NAV 계산 수치 검산 — 3종목×10거래일 합성 가격(첫날 NAV=1000, ffill, 휴장 갭, 수익률 경계)."""
from __future__ import annotations

import pytest

from nps_tracker.nav import (
    _evaluate_today,
    _mtd_pct,
    _nav_on_or_before,
    _today_change_pct,
    _ytd_pct,
    build_nav_history,
)

# 2026-01: 거래일 10일(주말 03-04, 10-11 휴장 갭 포함)
DAYS = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
        "2026-01-09", "2026-01-12", "2026-01-13", "2026-01-14", "2026-01-15"]

HOLDINGS = [
    {"stock_code": "AAA111", "stock_name": "에이", "shares": 100},
    {"stock_code": "BBB222", "stock_name": "비", "shares": 10},
    {"stock_code": "CCC333", "stock_name": "씨", "shares": 1000},
]


def _prices():
    # A: 100→109 매일 +1 | B: 01-06 누락(ffill 검증) | C: 10.0 고정
    a = [{"date": d, "close": 100.0 + i} for i, d in enumerate(DAYS)]
    a.insert(0, {"date": "2025-12-30", "close": 99.0})  # start_date 이전 → 제외돼야 함
    b_closes = {"2026-01-02": 1000.0, "2026-01-05": 1010.0, "2026-01-07": 1020.0,
                "2026-01-08": 1030.0, "2026-01-09": 1040.0, "2026-01-12": 1050.0,
                "2026-01-13": 1060.0, "2026-01-14": 1070.0, "2026-01-15": 1080.0}
    b = [{"date": d, "close": c} for d, c in b_closes.items()]
    c = [{"date": d, "close": 10.0} for d in DAYS]
    return {"AAA111": a, "BBB222": b, "CCC333": c}


def test_build_nav_history_numbers():
    hist = build_nav_history(HOLDINGS, _prices(), "2026-01-02", "2026-01-15")

    assert [s["date"] for s in hist] == DAYS  # start 이전 날짜 제외, 휴장일은 행 자체가 없음
    assert all(s["total_count"] == 3 for s in hist)

    # 첫날: 100*100 + 1000*10 + 10*1000 = 30,000 → NAV 1000 고정, units = 30
    assert hist[0]["total_value"] == 30_000
    assert hist[0]["nav"] == pytest.approx(1000.0)

    # 둘째 날(01-05): 10,100 + 10,100 + 10,000 = 30,200 → NAV = 30200/30
    assert hist[1]["total_value"] == 30_200
    assert hist[1]["nav"] == pytest.approx(30_200 / 30)

    # 셋째 날(01-06): B 가격 누락 → 01-05 종가 1010으로 ffill
    # 10,200 + 10,100 + 10,000 = 30,300
    assert hist[2]["total_value"] == 30_300
    assert hist[2]["nav"] == pytest.approx(1010.0)

    # 마지막 날(01-15): 10,900 + 10,800 + 10,000 = 31,700
    assert hist[-1]["total_value"] == 31_700
    assert hist[-1]["nav"] == pytest.approx(31_700 / 30)


def test_build_nav_history_empty_inputs():
    assert build_nav_history(HOLDINGS, {}, "2026-01-02", "2026-01-15") == []
    assert build_nav_history([], _prices(), "2026-01-02", "2026-01-15") == []
    # 범위 밖이면 빈 시계열
    assert build_nav_history(HOLDINGS, _prices(), "2027-01-01", "2027-12-31") == []


def test_nav_on_or_before():
    hist = [{"date": d, "nav": 1000.0 + i} for i, d in enumerate(DAYS)]
    assert _nav_on_or_before(hist, "2026-01-05")["date"] == "2026-01-05"  # 정확 일치
    assert _nav_on_or_before(hist, "2026-01-04")["date"] == "2026-01-02"  # 휴장일 → 직전 거래일
    assert _nav_on_or_before(hist, "2025-12-31") is None  # 이력 이전


def test_today_change_pct_weighted():
    holdings = [
        {"market_value": 100, "change_pct": 10.0},
        {"market_value": 300, "change_pct": -2.0},
        {"market_value": 50, "change_pct": None},  # 등락 없음 → 제외
        {"market_value": 0, "change_pct": 99.0},   # 평가액 0 → 제외
    ]
    assert _today_change_pct(holdings) == pytest.approx((10.0 * 100 - 2.0 * 300) / 400)
    assert _today_change_pct([]) is None


def test_mtd_pct_regular_month():
    hist = [
        {"date": "2026-01-30", "nav": 1100.0},
        {"date": "2026-02-02", "nav": 1111.0},
        {"date": "2026-02-03", "nav": 1122.0},
    ]
    # 전월 말일(01-31) 이하 최신 = 01-30 → 1122/1100 - 1
    assert _mtd_pct(hist, "2026-02-03") == pytest.approx((1122.0 / 1100.0 - 1) * 100)


def test_mtd_pct_january_uses_prev_year_end():
    hist = [
        {"date": "2025-12-30", "nav": 990.0},
        {"date": "2025-12-31", "nav": 1000.0},
        {"date": "2026-01-02", "nav": 1010.0},
    ]
    # 1월 → 직전 연말(2025-12-31) 기준
    assert _mtd_pct(hist, "2026-01-02") == pytest.approx(1.0)


def test_mtd_pct_no_reference():
    hist = [{"date": "2026-01-02", "nav": 1000.0}]
    assert _mtd_pct(hist, "2026-01-02") is None  # 전월 말 이전 데이터 없음


def test_ytd_pct_with_prev_year_data():
    hist = [
        {"date": "2025-12-30", "nav": 980.0},
        {"date": "2025-12-31", "nav": 1000.0},
        {"date": "2026-01-02", "nav": 1010.0},
        {"date": "2026-01-05", "nav": 1100.0},
    ]
    # 연초 이전 마지막(2025-12-31) 기준
    assert _ytd_pct(hist, "2026-01-05") == pytest.approx(10.0)


def test_ytd_pct_year_start_inside_history():
    # 연초 데이터가 이력의 시작인 경우: 첫 거래일이 기준
    hist = [
        {"date": "2026-01-02", "nav": 1010.0},
        {"date": "2026-01-05", "nav": 1111.0},
    ]
    assert _ytd_pct(hist, "2026-01-05") == pytest.approx((1111.0 / 1010.0 - 1) * 100)


def test_ytd_pct_single_point():
    assert _ytd_pct([{"date": "2026-01-02", "nav": 1000.0}], "2026-01-02") is None


def test_evaluate_today():
    prices = _prices()
    valid = _evaluate_today(HOLDINGS, prices, "2026-01-15")
    by_code = {h["stock_code"]: h for h in valid}

    assert by_code["AAA111"]["price"] == 109.0
    assert by_code["AAA111"]["market_value"] == 10_900
    assert by_code["AAA111"]["change_pct"] == pytest.approx((109.0 / 108.0 - 1) * 100)
    assert by_code["CCC333"]["change_pct"] == pytest.approx(0.0)

    # 가격 없는 종목은 평가에서 제외
    extra = HOLDINGS + [{"stock_code": "ZZZ999", "stock_name": "없음", "shares": 1}]
    assert {h["stock_code"] for h in _evaluate_today(extra, prices, "2026-01-15")} \
        == {"AAA111", "BBB222", "CCC333"}

    # 첫 거래일 기준이면 직전 종가가 없어 change_pct=None
    first = _evaluate_today([HOLDINGS[2]], prices, "2026-01-02")
    assert first[0]["change_pct"] is None
