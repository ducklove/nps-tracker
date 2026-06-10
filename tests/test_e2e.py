"""파이프라인 end-to-end — 모든 외부 소스를 monkeypatch한 소형 데이터로 cli.main() 전체 실행.

성공 경로: 세 산출물(data.js/data.json/current.json) 생성 + 계약 v2 필드 확인.
실패 경로: 가격 수신율 미달 → 검증 게이트가 발행을 막고 exit 2, 산출물 미생성.
"""
from __future__ import annotations

import json
import os

import pytest

from nps_tracker import cli, config

CODES = ("005930", "000660", "035420")
SRC_DATE = "2025-12-30"


def _mk_prices(codes=CODES):
    """src_date 종가 + 이후 6거래일, 일 +1%(검증 경고 안 뜨는 완만한 흐름)."""
    days = ["2025-12-30", "2026-01-02", "2026-01-05", "2026-01-06",
            "2026-01-07", "2026-01-08", "2026-01-09"]
    out = {}
    for j, code in enumerate(codes):
        base = 10_000 * (j + 1)
        out[code] = [{"date": d, "close": round(base * 1.01 ** i, 2)} for i, d in enumerate(days)]
    return out


def _public_rows():
    return [
        {"name": f"종목{j}", "stock_code": code, "source_market_value": (j + 1) * 10_000_000_000,
         "ownership_pct": 5.0 + j, "rank": j + 1}
        for j, code in enumerate(CODES)
    ]


@pytest.fixture
def pipeline(tmp_repo, monkeypatch):
    """외부 I/O 전부 차단: 공공데이터/FnGuide/가격/KOSPI/기금 모두 고정값."""
    prices = _mk_prices()
    monkeypatch.setattr(config, "MIN_RESOLVED_HOLDINGS", 2)  # 합성 3종목용 완화
    monkeypatch.setattr(cli, "get_public_holdings", lambda: (_public_rows(), SRC_DATE))
    monkeypatch.setattr(cli, "fetch_fnguide_shares", lambda resolver: {})
    monkeypatch.setattr(cli, "fetch_dart_nps_shares", lambda holdings: {})
    monkeypatch.setattr(cli, "get_prices_cached", lambda codes, since, until, refresh=False: dict(prices))
    monkeypatch.setattr(cli, "get_kospi_cached",
                        lambda since, until, refresh=False:
                        [{"date": "2026-01-08", "value": 2600.0}, {"date": "2026-01-09", "value": 2610.0}])
    monkeypatch.setattr(cli, "get_fund_portfolio", lambda nav_hist: {
        "unit": "won", "asOf": "2026-01", "monthlyFrom": "2026-01", "estimatedFrom": None,
        "series": [{"period": "2026-01", "total": 600, "domestic_stock": 100, "foreign_stock": 200,
                    "domestic_bond": 150, "foreign_bond": 50, "alternative": 80, "short_term": 20}],
    })
    return tmp_repo, prices


def test_e2e_success(pipeline):
    tmp, _ = pipeline
    cli.main([])

    raw = (tmp / "data.js").read_text(encoding="utf-8")
    assert raw.startswith("window.NPS_DATA = ") and raw.rstrip().endswith(";")
    data = json.loads(raw[len("window.NPS_DATA = "):].rstrip().rstrip(";"))
    # data.json == data.js 동일 객체
    assert json.loads((tmp / "data.json").read_text(encoding="utf-8")) == data

    # 계약 v2
    assert data["schemaVersion"] == 2
    assert data["composition"] == {"date": SRC_DATE, "source": "data.go.kr"}
    assert data["warnings"] == []  # 완만한 합성 데이터 → 경고 없음
    assert data["fundPortfolio"]["targets"] == config.FUND_TARGETS
    # 기존 필드 보존
    assert data["source"] == f"data.go.kr({SRC_DATE})"
    assert data["summary"]["asOf"] == "2026-01-09"
    assert data["summary"]["count"] == 3
    assert len(data["navHistory"]) == 7
    assert data["navHistory"][0]["nav"] == 1000.0
    assert [k["date"] for k in data["kospiHistory"]] == ["2026-01-08", "2026-01-09"]

    cur = json.loads((tmp / "current.json").read_text(encoding="utf-8"))
    assert cur["schemaVersion"] == 2 and len(cur["holdings"]) == 3
    assert os.path.exists(config.NAV_HISTORY)
    # 공공데이터 성공 경로 → seed 갱신
    seed = json.loads((tmp / "data" / "seed_holdings_latest.json").read_text(encoding="utf-8"))
    assert seed["date"] == SRC_DATE and len(seed["holdings"]) == 3


def test_e2e_dart_overrides_fnguide(pipeline, monkeypatch):
    """공시수량 우선순위: DART > FnGuide > 연말 추정. 둘 다 있는 종목은 DART 값이 이긴다."""
    tmp, _ = pipeline
    monkeypatch.setattr(cli, "fetch_fnguide_shares",
                        lambda resolver: {CODES[0]: 111_111, CODES[1]: 50_000})
    monkeypatch.setattr(cli, "fetch_dart_nps_shares",
                        lambda holdings: {CODES[0]: 999_999})
    cli.main([])
    cur = json.loads((tmp / "current.json").read_text(encoding="utf-8"))
    shares = {h["stock_code"]: h["shares"] for h in cur["holdings"]}
    assert shares[CODES[0]] == 999_999  # DART가 FnGuide(111,111)를 덮음
    assert shares[CODES[1]] == 50_000   # DART에 없는 종목은 FnGuide 값
    assert shares[CODES[2]] != 0        # 둘 다 없는 종목은 연말 추정수량 유지


def test_e2e_blocks_on_low_price_coverage(pipeline, monkeypatch):
    """seed 구성 3종목 중 1종목만 가격 수신 → 검증 게이트가 발행을 막고 exit 2."""
    tmp, prices = pipeline
    # 공공 경로 차단 + seed 구성 제공(가격 부족 시 공공 경로는 환산 단계에서 먼저 걸러지므로)
    monkeypatch.setattr(cli, "get_public_holdings", lambda: None)
    (tmp / "data" / "seed_holdings_latest.json").write_text(json.dumps({
        "date": SRC_DATE,
        "holdings": [{"stock_code": c, "stock_name": f"종목{j}", "shares": 100, "ownership_pct": 5.0}
                     for j, c in enumerate(CODES)],
    }, ensure_ascii=False), encoding="utf-8")
    poor = {CODES[0]: prices[CODES[0]]}  # 1/3 종목만 가격 수신 → coverage 미달
    monkeypatch.setattr(cli, "get_prices_cached", lambda codes, since, until, refresh=False: dict(poor))
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == 2
    assert not (tmp / "data.js").exists()  # 발행 중단 — 산출물 미생성
    assert not (tmp / "data.json").exists()
