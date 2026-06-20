from __future__ import annotations

from nps_tracker.sources.kis import (
    aggregate_pension_trade,
    extract_pension_trade_rows,
    get_pension_trade_trend,
)


def test_extract_pension_trade_rows_converts_fund_fields_to_krw():
    payload = {"output2": [
        {
            "stck_bsop_date": "20260619",
            "stck_clpr": "75000",
            "fund_ntby_qty": "-10",
            "fund_shnu_vol": "90",
            "fund_seln_vol": "100",
            "fund_ntby_tr_pbmn": "-750",
            "fund_shnu_tr_pbmn": "6750",
            "fund_seln_tr_pbmn": "7500",
        }
    ]}

    rows = extract_pension_trade_rows(payload)

    assert rows == [{
        "date": "2026-06-19",
        "close": 75000.0,
        "netShares": -10,
        "buyShares": 90,
        "sellShares": 100,
        "netValue": -750_000_000,
        "buyValue": 6_750_000_000,
        "sellValue": 7_500_000_000,
    }]


def test_aggregate_pension_trade_sums_by_date_and_latest():
    trend = aggregate_pension_trade(
        [
            ("005930", [
                {"date": "2026-06-18", "netValue": 100_000_000, "buyValue": 300_000_000,
                 "sellValue": 200_000_000, "netShares": 10, "buyShares": 30, "sellShares": 20},
                {"date": "2026-06-19", "netValue": -50_000_000, "buyValue": 150_000_000,
                 "sellValue": 200_000_000, "netShares": -5, "buyShares": 15, "sellShares": 20},
            ]),
            ("000660", [
                {"date": "2026-06-19", "netValue": 70_000_000, "buyValue": 170_000_000,
                 "sellValue": 100_000_000, "netShares": 7, "buyShares": 17, "sellShares": 10},
            ]),
        ],
        as_of="2026-06-19",
        total_value=10_000_000_000,
        eligible_count=3,
        queried_count=2,
        success_count=2,
        coverage_value=8_000_000_000,
        limit=2,
    )

    assert trend["asOf"] == "2026-06-19"
    assert trend["basis"]["coveragePct"] == 80.0
    assert trend["series"][0]["netValue"] == 100_000_000
    assert trend["series"][0]["symbols"] == 1
    assert trend["latest"]["netValue"] == 20_000_000
    assert trend["latest"]["netValuePct"] == 0.2
    assert trend["latest"]["symbols"] == 2


def test_get_pension_trade_trend_uses_configured_limit(monkeypatch):
    holdings = [
        {"stock_code": "005930", "market_value": 8_000_000_000},
        {"stock_code": "000660", "market_value": 2_000_000_000},
    ]
    calls = []

    def fetcher(symbol, base_date):
        calls.append((symbol, base_date))
        return {"output2": [
            {"stck_bsop_date": "20260619", "fund_ntby_tr_pbmn": "100"}
        ]}

    from nps_tracker import config

    monkeypatch.setattr(config, "KIS_PENSION_TRADE_LIMIT", 1)
    monkeypatch.setattr(config, "KIS_REQUEST_SLEEP_SEC", 0)

    trend = get_pension_trade_trend(
        holdings,
        "2026-06-19",
        total_value=10_000_000_000,
        fetcher=fetcher,
    )

    assert calls == [("005930", "20260619")]
    assert trend["latest"]["netValue"] == 100_000_000
    assert trend["basis"]["eligible"] == 2
    assert trend["basis"]["queried"] == 1


def test_get_pension_trade_trend_returns_error_when_all_kis_calls_fail(monkeypatch):
    holdings = [{"stock_code": "005930", "market_value": 10_000_000_000}]

    def fetcher(symbol, base_date):
        raise RuntimeError("HTTP 403: Forbidden")

    from nps_tracker import config

    monkeypatch.setattr(config, "KIS_PENSION_TRADE_LIMIT", 1)
    monkeypatch.setattr(config, "KIS_REQUEST_SLEEP_SEC", 0)

    trend = get_pension_trade_trend(
        holdings,
        "2026-06-19",
        total_value=10_000_000_000,
        fetcher=fetcher,
    )

    assert trend["status"] == "error"
    assert trend["error"] == "HTTP 403: Forbidden"
    assert trend["basis"]["queried"] == 1
    assert trend["basis"]["success"] == 0
    assert trend["series"] == []
