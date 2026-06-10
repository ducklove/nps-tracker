"""estimate_recent_months 규칙 검산 — 연 3% 복리, 환율·S&P 반영, 국내주식 레벨 정합."""
from __future__ import annotations

import pytest

from nps_tracker import fund

BASE = {
    "period": "2026-02", "source": "sheet",
    "domestic_bond": 1000, "alternative": 500, "short_term": 100,
    "foreign_bond": 200, "foreign_stock": 300, "domestic_stock": 400,
}

SP = {"2026-02": 5000.0, "2026-03": 5100.0, "2026-04": 5200.0}
USD = {"2026-02": 1300.0, "2026-03": 1325.0, "2026-04": 1350.0}

# 본 사이트 일별 국내주식 평가액(월말이 남도록 월중 값 포함)
NAV_HIST = [
    {"date": "2026-02-10", "total_value": 790},
    {"date": "2026-02-27", "total_value": 800},   # 기준월 월말 → ds_base
    {"date": "2026-03-31", "total_value": 820},
    {"date": "2026-04-15", "total_value": 830},
    {"date": "2026-04-30", "total_value": 840},
]


@pytest.fixture
def market(monkeypatch):
    monkeypatch.setattr(fund, "_fetch_market_monthly", lambda: (dict(SP), dict(USD)))


def test_estimate_two_months(market):
    series_map = {"2026-02": dict(BASE), "2025-12": {"period": "2025-12", "domestic_stock": 1}}
    out = fund.estimate_recent_months(series_map, NAV_HIST, "2026-04")

    assert [s["period"] for s in out] == ["2026-03", "2026-04"]
    assert all(s["estimated"] for s in out)

    m1 = out[0]  # 2026-03: m=1
    f3 = 1.03 ** (1 / 12)
    usd_r = USD["2026-03"] / USD["2026-02"]
    sp_r = SP["2026-03"] / SP["2026-02"]
    assert m1["domestic_bond"] == round(1000 * f3) == 1002
    assert m1["alternative"] == round(500 * f3) == 501
    assert m1["short_term"] == round(100 * f3) == 100
    assert m1["foreign_bond"] == round(200 * usd_r * f3) == 204
    assert m1["foreign_stock"] == round(300 * sp_r * usd_r) == 312
    assert m1["domestic_stock"] == round(400 * 820 / 800) == 410  # 본 사이트 월말 변화율 반영

    m2 = out[1]  # 2026-04: m=2 (복리)
    f3_2 = 1.03 ** (2 / 12)
    assert m2["domestic_bond"] == round(1000 * f3_2)
    assert m2["foreign_stock"] == round(300 * (5200 / 5000) * (1350 / 1300))
    assert m2["domestic_stock"] == round(400 * 840 / 800) == 420


def test_estimate_missing_market_month_falls_back_to_base(market):
    # 2026-05는 SP/USD에 없음 → 비율 1로 유지(환율·지수 변화 없음 가정), 3% 복리만 적용
    out = fund.estimate_recent_months({"2026-02": dict(BASE)}, NAV_HIST, "2026-05")
    m3 = out[-1]
    assert m3["period"] == "2026-05"
    f3_3 = 1.03 ** (3 / 12)
    assert m3["foreign_bond"] == round(200 * 1.0 * f3_3)
    assert m3["foreign_stock"] == round(300 * 1.0 * 1.0)
    # 2026-05 국내주식 월말값 없음 → 기준월 레벨 유지
    assert m3["domestic_stock"] == 400


def test_estimate_no_domestic_history_keeps_base_level(market):
    out = fund.estimate_recent_months({"2026-02": dict(BASE)}, None, "2026-03")
    assert out[0]["domestic_stock"] == 400


def test_estimate_until_not_after_base(market):
    assert fund.estimate_recent_months({"2026-02": dict(BASE)}, NAV_HIST, "2026-02") == []
    assert fund.estimate_recent_months({"2026-02": dict(BASE)}, NAV_HIST, "2026-01") == []


def test_estimate_skips_without_base_market_data(monkeypatch):
    # 기준월 시장지표가 없으면 추정 생략(헛값 금지)
    monkeypatch.setattr(fund, "_fetch_market_monthly", lambda: ({}, {}))
    assert fund.estimate_recent_months({"2026-02": dict(BASE)}, NAV_HIST, "2026-04") == []


def test_estimate_ignores_estimated_rows_for_base(market):
    # estimated 행은 공표 기준월 선정에서 제외 → base는 2026-02
    series_map = {
        "2026-02": dict(BASE),
        "2026-03": {"period": "2026-03", "estimated": True, "domestic_stock": 9999},
    }
    out = fund.estimate_recent_months(series_map, NAV_HIST, "2026-03")
    assert [s["period"] for s in out] == ["2026-03"]
    assert out[0]["domestic_stock"] == round(400 * 820 / 800)  # 추정행이 base가 되지 않음


def test_month_helpers():
    assert fund._month_add("2026-12", 1) == "2027-01"
    assert fund._month_add("2026-01", -1) == "2025-12"
    assert fund._months_between("2026-02", "2026-04") == 2
    assert fund._domestic_stock_by_month(NAV_HIST) == {"2026-02": 800, "2026-03": 820, "2026-04": 840}
