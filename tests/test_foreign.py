"""해외주식 스냅샷(F-9) — CSV 파싱(헤더 변동 흡수)·seed 폴백·발행 형태. 전부 오프라인."""
from __future__ import annotations

import json

import pytest

from nps_tracker import config
from nps_tracker.sources import datago

CSV = """﻿번호,종목명,평가액(억 원),자산군 내 비중(퍼센트),지분율(퍼센트)
1,APPLE INC,"30,000",4.5,0.31
2,MICROSOFT CORP,"25,000",3.8,0.28
3,잡음행,,,
"""


def test_fetch_foreign_holdings_parses_csv(tmp_repo, monkeypatch):
    page = '{"contentUrl":"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=F1&amp;fileDetailSn=1"}' \
           ' 국민연금공단_해외주식 투자정보_20251231'
    def fake_download(url, **kw):
        return page.encode() if "fileData.do" in url else CSV.encode("utf-8")
    monkeypatch.setattr(datago, "_download", fake_download)
    rows, src_date = datago.fetch_foreign_holdings()
    assert src_date == "2025-12-31"
    assert [r["name"] for r in rows] == ["APPLE INC", "MICROSOFT CORP"]  # 평가액 내림차순·잡음행 제외
    assert rows[0]["value"] == 30_000 * 100_000_000
    assert rows[0]["weight_pct"] == 4.5 and rows[0]["ownership_pct"] == 0.31


def test_get_foreign_holdings_saves_seed_and_shapes(tmp_repo, monkeypatch):
    monkeypatch.setattr(datago, "fetch_foreign_holdings", lambda: (
        [{"name": "APPLE INC", "value": 3_000_000_000_000, "weight_pct": 4.5, "ownership_pct": 0.31}],
        "2025-12-31"))
    out = datago.get_foreign_holdings()
    assert out["date"] == "2025-12-31" and out["count"] == 1
    assert out["total"] == 3_000_000_000_000
    assert out["holdings"][0] == {"name": "APPLE INC", "value": 3_000_000_000_000,
                                  "weightPct": 4.5, "ownershipPct": 0.31,
                                  "country": "미국", "ticker": "AAPL"}
    seed = json.load(open(config.SEED_FOREIGN, encoding="utf-8"))
    assert seed["date"] == "2025-12-31" and len(seed["holdings"]) == 1


def test_get_foreign_holdings_seed_fallback(tmp_repo, monkeypatch):
    def boom():
        raise RuntimeError("net down")
    monkeypatch.setattr(datago, "fetch_foreign_holdings", boom)
    assert datago.get_foreign_holdings() is None  # seed도 없으면 None(섹션 숨김)
    with open(config.SEED_FOREIGN, "w", encoding="utf-8") as f:
        json.dump({"date": "2024-12-31", "holdings": [
            {"name": "TESLA INC", "value": 1_000_000_000_000, "weight_pct": 1.2, "ownership_pct": 0.1}]}, f)
    out = datago.get_foreign_holdings()
    assert out["date"] == "2024-12-31" and out["holdings"][0]["name"] == "TESLA INC"


def test_foreign_top_n_limit(tmp_repo, monkeypatch):
    monkeypatch.setattr(config, "FOREIGN_TOP_N", 2)
    monkeypatch.setattr(datago, "fetch_foreign_holdings", lambda: (
        [{"name": f"S{i}", "value": (9 - i) * 1e8, "weight_pct": None, "ownership_pct": None}
         for i in range(5)], "2025-12-31"))
    out = datago.get_foreign_holdings()
    assert out["count"] == 5 and len(out["holdings"]) == 2  # count는 전체, 목록은 상위 N


def test_foreign_current_estimates(tmp_repo, monkeypatch):
    monkeypatch.setattr(datago, "fetch_foreign_holdings", lambda: (
        [{"name": "APPLE INC", "value": 3_000_000_000_000, "weight_pct": 4.5, "ownership_pct": 0.31}],
        "2025-12-31"))
    monkeypatch.setattr(datago, "fetch_foreign_market_data", lambda rows, src_date, as_of: {
        "APPLE INC": {
            "ticker": "AAPL",
            "country": "미국",
            "currency": "USD",
            "priceScale": 1.0,
            "sourcePrice": 100.0,
            "sourcePriceDate": "2025-12-31",
            "sourceFx": 1000.0,
            "sourceFxDate": "2025-12-31",
            "currentPrice": 200.0,
            "currentPriceDate": "2026-01-09",
            "currentFx": 1200.0,
            "currentFxDate": "2026-01-09",
        }
    })
    out = datago.get_foreign_holdings(as_of="2026-01-09", foreign_stock_total=100_000_000_000_000)
    h = out["holdings"][0]
    assert out["asOf"] == "2026-01-09"
    assert out["currentPricedCount"] == 1
    assert h["estimatedShares"] == 30_000_000
    assert h["currentValue"] == 7_200_000_000_000
    assert h["currentWeightPct"] == pytest.approx(7.2)
