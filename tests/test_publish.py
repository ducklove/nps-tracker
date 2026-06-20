"""발행 계약 — data.js/data.json/current.json: 기존 필드 보존 + v2 추가 필드."""
from __future__ import annotations

import json

import pytest

from nps_tracker import config
from nps_tracker.publish import _composition, write_outputs

HIST = [
    {"date": "2026-06-05", "total_value": 30_000, "nav": 1000.0, "total_count": 2},
    {"date": "2026-06-08", "total_value": 30_600, "nav": 1020.123456, "total_count": 2},
    {"date": "2026-06-09", "total_value": 31_000, "nav": 1033.333333, "total_count": 2},
]
KOSPI = [{"date": "2026-06-08", "value": 8000.0}, {"date": "2026-06-09", "value": 8096.93}]
FUND = {"unit": "won", "asOf": "2026-02", "monthlyFrom": "2025-12", "estimatedFrom": None,
        "series": [{"period": "2026-02", "domestic_stock": 100, "foreign_stock": 200,
                    "domestic_bond": 50, "foreign_bond": 25, "alternative": 60,
                    "short_term": 5, "total": 440}]}
PENSION_TRADE = {
    "source": "KIS Open API",
    "asOf": "2026-06-09",
    "latest": {"date": "2026-06-09", "netValue": 123_000_000, "symbols": 2},
    "basis": {"eligible": 2, "queried": 2, "success": 2, "coveragePct": 100.0},
    "series": [{"date": "2026-06-09", "netValue": 123_000_000, "symbols": 2}],
}


def _holdings():
    return [
        {"stock_code": "005930", "stock_name": "삼성전자", "shares": 100, "ownership_pct": 7.26,
         "price": 200.0, "market_value": 20_000, "change_pct": 1.5},
        {"stock_code": "000660", "stock_name": "SK하이닉스", "shares": 10, "ownership_pct": 6.4,
         "price": 1100.0, "market_value": 11_000, "change_pct": -0.5},
    ]


@pytest.fixture
def published(tmp_repo):
    write_outputs("2026-06-09", "seed(2024-12-31)", _holdings(), 31_000, 1033.333333,
                  1.2, 3.4, 5.6, HIST, KOSPI, fund_portfolio=FUND, warnings=["경고1"])
    data_js = (tmp_repo / "data.js").read_text(encoding="utf-8")
    data_json = json.loads((tmp_repo / "data.json").read_text(encoding="utf-8"))
    current = json.loads((tmp_repo / "current.json").read_text(encoding="utf-8"))
    nav_hist = json.loads((tmp_repo / "data" / "nav_history.json").read_text(encoding="utf-8"))
    return tmp_repo, data_js, data_json, current, nav_hist


def test_data_js_wrapper_and_data_json_identical(published):
    _, data_js, data_json, _, _ = published
    assert data_js.startswith("window.NPS_DATA = ")
    assert data_js.endswith(";\n")
    embedded = json.loads(data_js[len("window.NPS_DATA = "):].rstrip().rstrip(";"))
    assert embedded == data_json  # data.json은 data.js와 동일 객체


def test_existing_fields_preserved(published):
    _, _, data_json, current, nav_hist = published
    # data.js/data.json 기존 키
    for key in ("lastUpdated", "asOf", "source", "summary", "holdings", "holdingsTotal",
                "navHistory", "kospiHistory", "treemap", "fundPortfolio"):
        assert key in data_json, key
    assert data_json["asOf"] == "2026-06-09"
    assert data_json["source"] == "seed(2024-12-31)"
    assert data_json["summary"] == {
        "totalValue": 31_000, "nav": 1033.33, "count": 2, "todayPct": 1.2,
        "mtdPct": 3.4, "ytdPct": 5.6, "asOf": "2026-06-09",
    }
    assert data_json["holdingsTotal"] == 2
    assert data_json["navHistory"] == [
        {"date": "2026-06-05", "nav": 1000.0},
        {"date": "2026-06-08", "nav": 1020.1235},  # 4자리 반올림
        {"date": "2026-06-09", "nav": 1033.3333},
    ]
    assert data_json["kospiHistory"] == KOSPI
    assert data_json["treemap"][0] == {"name": "삼성전자", "value": 20_000, "changePct": 1.5,
                                       "sector": None}  # sector는 v2 추가(미매핑 시 null)

    # current.json 기존 키(순서 포함 앞쪽 유지) — 한 글자도 변경 금지
    assert list(current.keys())[:6] == ["lastUpdated", "asOf", "source", "summary",
                                        "allocation", "holdings"]
    assert current["summary"] == data_json["summary"]
    assert len(current["holdings"]) == 2  # current.json은 전체 보유내역
    top = current["holdings"][0]
    assert top["stock_code"] == "005930" and top["price"] == 200.0
    assert top["weight"] == pytest.approx(20_000 / 31_000 * 100)
    assert current["allocation"]["asOf"] == "2026-02"

    # data/nav_history.json은 풀 정밀도 유지
    assert nav_hist[-1] == {"date": "2026-06-09", "total_value": 31_000,
                            "nav": 1033.333333, "total_count": 2}


def test_v2_fields_added(published):
    _, _, data_json, current, _ = published
    for out in (data_json, current):
        assert out["schemaVersion"] == 2
        assert out["composition"] == {"date": "2024-12-31", "source": "seed"}
        assert out["warnings"] == ["경고1"]
    fp = data_json["fundPortfolio"]
    assert fp["targets"] == config.FUND_TARGETS
    assert fp["targetsNote"] == "중기 자산배분 목표"
    # 원본 fundPortfolio 필드도 그대로
    assert fp["series"] == FUND["series"] and fp["asOf"] == "2026-02"
    # 호출자가 넘긴 dict는 오염시키지 않는다
    assert "targets" not in FUND


def test_pension_trade_added_to_outputs(tmp_repo):
    write_outputs("2026-06-09", "seed(2024-12-31)", _holdings(), 31_000, 1033.33,
                  None, None, None, HIST, [], fund_portfolio=None,
                  pension_trade=PENSION_TRADE)
    data_json = json.loads((tmp_repo / "data.json").read_text(encoding="utf-8"))
    current = json.loads((tmp_repo / "current.json").read_text(encoding="utf-8"))
    assert data_json["pensionTrade"] == PENSION_TRADE
    assert current["pensionTrade"] == PENSION_TRADE


def test_holdings_sorted_and_weighted(published):
    _, _, data_json, _, _ = published
    mvs = [h["market_value"] for h in data_json["holdings"]]
    assert mvs == sorted(mvs, reverse=True)
    assert sum(h["weight"] for h in data_json["holdings"]) == pytest.approx(100.0)


def test_without_fund_portfolio_and_warnings(tmp_repo):
    write_outputs("2026-06-09", "data.go.kr(2025-12-31)", _holdings(), 31_000, 1033.33,
                  None, None, None, HIST, [], fund_portfolio=None)
    data_json = json.loads((tmp_repo / "data.json").read_text(encoding="utf-8"))
    current = json.loads((tmp_repo / "current.json").read_text(encoding="utf-8"))
    assert data_json["fundPortfolio"] is None  # targets는 fundPortfolio 있을 때만
    assert data_json["warnings"] == []
    assert data_json["composition"] == {"date": "2025-12-31", "source": "data.go.kr"}
    assert current["allocation"] is None


def test_top_n_truncation(tmp_repo):
    many = [{"stock_code": f"{i:06d}", "stock_name": f"종목{i}", "shares": 1, "ownership_pct": 0,
             "price": 1.0, "market_value": 1000 - i, "change_pct": 0.0}
            for i in range(config.TOP_N + 20)]
    write_outputs("2026-06-09", "seed(2024-12-31)", many, 1, 1000.0,
                  None, None, None, HIST, [], None)
    data_json = json.loads((tmp_repo / "data.json").read_text(encoding="utf-8"))
    current = json.loads((tmp_repo / "current.json").read_text(encoding="utf-8"))
    assert len(data_json["holdings"]) == config.TOP_N  # 초기 로딩은 TOP_N만
    assert data_json["holdingsTotal"] == config.TOP_N + 20
    assert len(current["holdings"]) == config.TOP_N + 20  # 전체는 current.json에


def test_composition_parser():
    assert _composition("seed(2024-12-31)") == {"date": "2024-12-31", "source": "seed"}
    assert _composition("data.go.kr(2025-12-31)") == {"date": "2025-12-31", "source": "data.go.kr"}
    assert _composition("이상한값") == {"date": None, "source": "이상한값"}
