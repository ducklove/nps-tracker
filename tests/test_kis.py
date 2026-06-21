from __future__ import annotations

from nps_tracker.sources import kis
from nps_tracker.sources.kis import (
    aggregate_pension_trade,
    extract_pension_trade_rows,
    get_market_pension_trade_trend,
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


def test_market_pension_trade_trend_sums_kospi_and_kosdaq():
    calls = []

    def fetcher(market, base_date):
        calls.append((market, base_date))
        values = {
            "KOSPI": [("20260618", "-192900"), ("20260619", "-526700")],
            "KOSDAQ": [("20260618", "31090"), ("20260619", "-12507")],
        }[market]
        return {"output": [
            {"stck_bsop_date": d, "fund_ntby_qty": "0", "fund_ntby_tr_pbmn": v}
            for d, v in values
        ]}

    trend = get_market_pension_trade_trend(
        "2026-06-19",
        total_value=10_000_000_000_000,
        fetcher=fetcher,
    )

    assert calls == [("KOSPI", "20260619"), ("KOSDAQ", "20260619")]
    assert trend["endpoint"] == "inquire-investor-daily-by-market"
    assert trend["trId"] == "FHPTJ04040000"
    assert trend["basis"]["aggregation"] == "KOSPI + KOSDAQ markets"
    assert trend["basis"]["queried"] == 2
    assert trend["basis"]["success"] == 2
    assert trend["latest"]["date"] == "2026-06-19"
    assert trend["latest"]["netValue"] == -539_207_000_000
    assert trend["latest"]["marketValues"] == {
        "KOSPI": -526_700_000_000,
        "KOSDAQ": -12_507_000_000,
    }
    assert trend["latest"]["netValuePct"] == -5.39207


def test_get_pension_trade_trend_defaults_to_market_fetcher():
    def market_fetcher(market, base_date):
        return {"output": [
            {"stck_bsop_date": "20260619", "fund_ntby_qty": "0", "fund_ntby_tr_pbmn": "1"}
        ]}

    trend = get_pension_trade_trend(
        [{"stock_code": "005930", "market_value": 10_000_000_000}],
        "2026-06-19",
        market_fetcher=market_fetcher,
    )

    assert trend["endpoint"] == "inquire-investor-daily-by-market"
    assert trend["latest"]["netValue"] == 2_000_000
    assert trend["basis"]["success"] == 2


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


def test_load_dotenv_recovers_wrapped_kis_app_secret(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "\n".join([
            "KIS_APP_KEY=app-key",
            "KIS_APP_SECRET=first",
            "middle",
            "last/part=",
            'KIS_ACCESS_TOKEN=""',
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(kis.config, "ROOT", str(tmp_path))
    monkeypatch.setattr(kis, "_DOTENV_CACHE", None)

    env = kis._load_dotenv()

    assert env["KIS_APP_SECRET"] == "firstmiddlelast/part="
    assert "last/part" not in env
    assert env["KIS_ACCESS_TOKEN"] == ""


def test_credentials_compact_secret_whitespace(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", " app\n key ")
    monkeypatch.setenv("KIS_APP_SECRET", " sec\n ret ")
    monkeypatch.setattr(kis, "_DOTENV_CACHE", None)

    assert kis._credentials() == ("appkey", "secret")


def test_kis_base_url_can_come_from_dotenv(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("KIS_BASE_URL=https://example.test:9443\n", encoding="utf-8")
    monkeypatch.delenv("KIS_BASE_URL", raising=False)
    monkeypatch.setattr(kis.config, "ROOT", str(tmp_path))
    monkeypatch.setattr(kis, "_DOTENV_CACHE", None)

    assert kis._kis_base_url() == "https://example.test:9443"
