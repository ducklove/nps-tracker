"""검증 게이트 — 에러/경고 각 조건의 발동·비발동."""
from __future__ import annotations

from nps_tracker import config
from nps_tracker.validate import run_validation

DAYS = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
        "2026-06-08", "2026-06-09"]


def _nav_hist(navs=None):
    navs = navs or [1000.0 + i for i in range(len(DAYS))]
    return [{"date": d, "nav": n, "total_value": round(n * 30)} for d, n in zip(DAYS, navs)]


def _holdings(n=3):
    return [{"stock_code": f"C{i:05d}", "stock_name": f"종목{i}", "shares": 10} for i in range(n)]


def _prices(codes, days=DAYS):
    return {c: [{"date": d, "close": 100.0} for d in days] for c in codes}


def _evaluated(holdings, change_pct=1.0, market_value=1000):
    return [dict(h, price=100.0, change_pct=change_pct, market_value=market_value) for h in holdings]


def _run(**over):
    holdings = over.pop("holdings", _holdings())
    kw = dict(
        holdings=holdings,
        evaluated=over.pop("evaluated", _evaluated(holdings)),
        prices=over.pop("prices", _prices([h["stock_code"] for h in holdings])),
        nav_hist=over.pop("nav_hist", _nav_hist()),
        prev_dates=over.pop("prev_dates", set(DAYS)),
        total_value=over.pop("total_value", 30_000),
        snap_date=over.pop("snap_date", DAYS[-1]),
        src_date=over.pop("src_date", "2025-12-31"),
        limit_used=over.pop("limit_used", False),
    )
    assert not over, f"알 수 없는 인자: {over}"
    return run_validation(**kw)


def test_all_green():
    errors, warnings = _run()
    assert errors == [] and warnings == []


# ---------- errors ----------
def test_empty_nav_hist_is_error():
    errors, _ = _run(nav_hist=[])
    assert any("비어" in e for e in errors)


def test_price_coverage_error_and_limit_skip():
    holdings = _holdings(20)
    prices = _prices([h["stock_code"] for h in holdings[:18]])  # 18/20 = 0.9 < 0.95
    errors, _ = _run(holdings=holdings, evaluated=_evaluated(holdings[:18]), prices=prices)
    assert any("가격 수신 종목 비율" in e for e in errors)
    # --limit 사용 시 이 검사는 생략
    errors, _ = _run(holdings=holdings, evaluated=_evaluated(holdings[:18]), prices=prices,
                     limit_used=True)
    assert not any("가격 수신 종목 비율" in e for e in errors)


def test_price_coverage_pass_at_threshold():
    holdings = _holdings(20)
    prices = _prices([h["stock_code"] for h in holdings[:19]])  # 0.95 == 임계 → 통과
    errors, _ = _run(holdings=holdings, evaluated=_evaluated(holdings[:19]), prices=prices)
    assert errors == []


def test_total_value_zero_is_error():
    errors, _ = _run(total_value=0)
    assert any("total_value" in e for e in errors)


def test_new_date_nav_jump_over_20pct_is_error():
    navs = [1000.0] * 6 + [1300.0]  # 마지막 날 +30%
    errors, warnings = _run(nav_hist=_nav_hist(navs), prev_dates=set(DAYS[:-1]))
    assert any("2026-06-09" in e and "+30.0%" in e for e in errors)
    assert not warnings  # 에러로 격상됐으므로 경고는 아님


def test_old_date_nav_jump_is_ignored():
    # 기존 발행 이력에 있던 날짜의 ±8% 변동(2026-06-08/09 사례)은 검사하지 않는다
    navs = [1000.0, 1000.0, 1000.0, 1000.0, 3588.0, 3288.0, 3563.0]
    errors, warnings = _run(nav_hist=_nav_hist(navs), prev_dates=set(DAYS), total_value=1)
    assert not any("일간 NAV" in e for e in errors)
    assert not any("일간 NAV" in w for w in warnings)


# ---------- warnings ----------
def test_new_date_nav_change_over_7pct_is_warning():
    navs = [1000.0] * 6 + [1084.0]  # 마지막 날 +8.4%
    errors, warnings = _run(nav_hist=_nav_hist(navs), prev_dates=set(DAYS[:-1]))
    assert errors == []
    assert any(w.startswith("2026-06-09 일간 NAV +8.4%") for w in warnings)
    # 7% 이하면 경고 없음
    navs = [1000.0] * 6 + [1069.0]
    _, warnings = _run(nav_hist=_nav_hist(navs), prev_dates=set(DAYS[:-1]))
    assert not any("일간 NAV" in w for w in warnings)


def test_stock_over_price_limit_is_warning():
    holdings = _holdings(3)
    evaluated = _evaluated(holdings)
    evaluated[0]["change_pct"] = 31.0   # 가격제한폭 초과
    evaluated[1]["change_pct"] = -45.0
    evaluated[2]["change_pct"] = 29.9   # 한도 내
    _, warnings = _run(holdings=holdings, evaluated=evaluated)
    w = next(w for w in warnings if "초과" in w and "종목" in w)
    assert "2종목" in w and "종목0" in w and "종목1" in w and "종목2" not in w
    assert "-45.0%" in w  # 절대값 큰 순 정렬·수치 표기


def test_stock_limit_warning_caps_names():
    holdings = _holdings(15)
    evaluated = _evaluated(holdings, change_pct=40.0)
    _, warnings = _run(holdings=holdings, evaluated=evaluated)
    w = next(w for w in warnings if "15종목" in w)
    assert w.count("종목") >= config.STOCK_LIMIT_WARN_MAX  # 나열은 최대 10개
    assert sum(1 for i in range(15) if f"종목{i} " in w) == config.STOCK_LIMIT_WARN_MAX


def test_stale_price_warning():
    holdings = _holdings(3)
    codes = [h["stock_code"] for h in holdings]
    # 거래일 12일 캘린더
    days = [f"2026-06-{d:02d}" for d in (1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 15, 16)]
    prices = _prices(codes, days)
    prices[codes[0]] = [{"date": days[0], "close": 100.0}]  # 첫날 이후 가격 없음 → 11거래일 스테일
    nav_hist = [{"date": d, "nav": 1000.0, "total_value": 1} for d in days]
    evaluated = _evaluated(holdings)  # 각 1/3 비중(≥0.1%)
    _, warnings = _run(holdings=holdings, evaluated=evaluated, prices=prices,
                       nav_hist=nav_hist, prev_dates=set(days), snap_date=days[-1])
    w = next(w for w in warnings if "스테일" in w)
    assert "1종목" in w and "종목0" in w and "거래정지/상폐 의심" in w

    # 비중이 0.1% 미만이면 경고 대상 아님
    evaluated[0]["market_value"] = 1  # 1/2001 ≈ 0.05%
    _, warnings = _run(holdings=holdings, evaluated=evaluated, prices=prices,
                       nav_hist=nav_hist, prev_dates=set(days), snap_date=days[-1])
    assert not any("스테일" in w for w in warnings)


def test_stale_price_not_triggered_under_threshold():
    holdings = _holdings(2)
    codes = [h["stock_code"] for h in holdings]
    prices = _prices(codes)
    prices[codes[0]] = [{"date": d, "close": 100.0} for d in DAYS[:-2]]  # 2거래일 뒤처짐 < 10
    _, warnings = _run(holdings=holdings, evaluated=_evaluated(holdings), prices=prices)
    assert not any("스테일" in w for w in warnings)


def test_composition_age_warning():
    # 2024-12-31 → 2026-06-09 = 525일 경과 > 400
    _, warnings = _run(src_date="2024-12-31")
    assert any("2024-12-31" in w and "525일" in w for w in warnings)
    # 400일 이내면 경고 없음
    _, warnings = _run(src_date="2025-12-31")
    assert not any("연말 공시 기준" in w for w in warnings)
