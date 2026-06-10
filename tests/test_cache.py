"""가격 증분 캐시 — 병합·증분 조회 구간 계산·재조회 규칙 (가격 fetcher monkeypatch)."""
from __future__ import annotations

import json

from nps_tracker import config
from nps_tracker.sources import market


def _rows(*pairs):
    return [{"date": d, "close": c} for d, c in pairs]


def _write_cache(payload):
    with open(config.PRICE_CACHE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def _read_cache():
    with open(config.PRICE_CACHE, encoding="utf-8") as f:
        return json.load(f)


class Recorder:
    """fetch_prices_pykrx 대역 — 호출 구간을 기록하고 준비된 데이터의 구간 내 행만 반환."""

    def __init__(self, data):
        self.data = data
        self.calls = []

    def __call__(self, codes, since, until):
        self.calls.append((tuple(codes), since, until))
        out = {}
        for c in codes:
            rows = [r for r in self.data.get(c, []) if since <= r["date"] <= until]
            if rows:
                out[c] = rows
        return out


def test_no_cache_full_fetch_and_save(tmp_repo, monkeypatch):
    rec = Recorder({"A": _rows(("2026-01-02", 100.0), ("2026-01-05", 101.0))})
    monkeypatch.setattr(market, "fetch_prices_pykrx", rec)
    monkeypatch.setattr(market, "fetch_prices_yf", lambda *a: {})

    out = market.get_prices_cached(["A"], "2026-01-01", "2026-01-05")

    assert rec.calls == [(("A",), "2026-01-01", "2026-01-05")]  # 캐시 없음 → 전체 조회
    assert out["A"] == _rows(("2026-01-02", 100.0), ("2026-01-05", 101.0))
    cache = _read_cache()
    assert cache["A"] == out["A"]
    assert cache["_meta"]["since"] == "2026-01-01"


def test_incremental_fetch_from_last_cached_date(tmp_repo, monkeypatch):
    _write_cache({"A": _rows(("2026-01-02", 100.0), ("2026-01-05", 101.0)),
                  "_meta": {"since": "2026-01-01"}})
    rec = Recorder({"A": _rows(("2026-01-06", 102.0), ("2026-01-07", 103.0))})
    monkeypatch.setattr(market, "fetch_prices_pykrx", rec)
    monkeypatch.setattr(market, "fetch_prices_yf", lambda *a: {})

    out = market.get_prices_cached(["A"], "2026-01-01", "2026-01-07")

    # 캐시 마지막(01-05) 다음 날부터만 조회 — 과거 날짜 재조회 금지
    assert rec.calls == [(("A",), "2026-01-06", "2026-01-07")]
    assert [r["date"] for r in out["A"]] == ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
    assert _read_cache()["A"] == out["A"]


def test_cache_hit_no_fetch(tmp_repo, monkeypatch):
    _write_cache({"A": _rows(("2026-01-02", 100.0), ("2026-01-07", 101.0)),
                  "_meta": {"since": "2026-01-01"}})
    rec = Recorder({})
    monkeypatch.setattr(market, "fetch_prices_pykrx", rec)
    monkeypatch.setattr(market, "fetch_prices_yf", lambda *a: {})

    out = market.get_prices_cached(["A"], "2026-01-01", "2026-01-07")
    assert rec.calls == []  # until까지 캐시 커버 → 조회 없음
    assert [r["date"] for r in out["A"]] == ["2026-01-02", "2026-01-07"]


def test_meta_covers_head_gap(tmp_repo, monkeypatch):
    """since가 휴장일이라 캐시 첫 종가가 since 뒤에 있어도, _meta가 커버를 보증하면 증분만."""
    _write_cache({"A": _rows(("2026-01-05", 100.0)),  # 첫 종가가 since(01-01)보다 뒤
                  "_meta": {"since": "2026-01-01"}})
    rec = Recorder({"A": _rows(("2026-01-06", 101.0))})
    monkeypatch.setattr(market, "fetch_prices_pykrx", rec)
    monkeypatch.setattr(market, "fetch_prices_yf", lambda *a: {})

    market.get_prices_cached(["A"], "2026-01-01", "2026-01-06")
    assert rec.calls == [(("A",), "2026-01-06", "2026-01-06")]


def test_cache_starting_late_triggers_full_refetch(tmp_repo, monkeypatch):
    """캐시 첫 날짜 > since이고 _meta 보증도 없으면 부족 구간을 채우러 전체 재조회."""
    _write_cache({"A": _rows(("2026-01-05", 999.0))})  # _meta 없음
    rec = Recorder({"A": _rows(("2026-01-02", 90.0), ("2026-01-05", 100.0))})
    monkeypatch.setattr(market, "fetch_prices_pykrx", rec)
    monkeypatch.setattr(market, "fetch_prices_yf", lambda *a: {})

    out = market.get_prices_cached(["A"], "2026-01-01", "2026-01-05")

    assert rec.calls == [(("A",), "2026-01-01", "2026-01-05")]
    # 병합 시 같은 날짜는 캐시 값 우선(이력 재현성): 01-05는 999 유지
    assert out["A"] == _rows(("2026-01-02", 90.0), ("2026-01-05", 999.0))


def test_refresh_ignores_and_replaces_cache(tmp_repo, monkeypatch):
    _write_cache({"A": _rows(("2026-01-02", 999.0), ("2026-01-05", 999.0)),
                  "_meta": {"since": "2026-01-01"}})
    rec = Recorder({"A": _rows(("2026-01-02", 100.0), ("2026-01-05", 101.0))})
    monkeypatch.setattr(market, "fetch_prices_pykrx", rec)
    monkeypatch.setattr(market, "fetch_prices_yf", lambda *a: {})

    out = market.get_prices_cached(["A"], "2026-01-01", "2026-01-05", refresh=True)

    assert rec.calls == [(("A",), "2026-01-01", "2026-01-05")]  # 캐시 무시, 전체 재조회
    assert out["A"] == _rows(("2026-01-02", 100.0), ("2026-01-05", 101.0))  # 새 값으로 교체
    assert _read_cache()["A"] == out["A"]


def test_mixed_codes_grouped_by_fetch_start(tmp_repo, monkeypatch):
    _write_cache({"B": _rows(("2026-01-02", 50.0), ("2026-01-05", 51.0)),
                  "_meta": {"since": "2026-01-01"}})
    rec = Recorder({
        "A": _rows(("2026-01-02", 100.0), ("2026-01-07", 103.0)),
        "B": _rows(("2026-01-06", 52.0), ("2026-01-07", 53.0)),
    })
    monkeypatch.setattr(market, "fetch_prices_pykrx", rec)
    monkeypatch.setattr(market, "fetch_prices_yf", lambda *a: {})

    out = market.get_prices_cached(["A", "B"], "2026-01-01", "2026-01-07")

    # A=캐시 없음 → 전체, B=증분(01-06~) — 시작일별 그룹 조회
    assert sorted(rec.calls) == [(("A",), "2026-01-01", "2026-01-07"),
                                 (("B",), "2026-01-06", "2026-01-07")]
    assert [r["date"] for r in out["B"]] == ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
    cache = _read_cache()
    assert set(cache) == {"A", "B", "_meta"}


def test_yfinance_fallback_for_missing_codes(tmp_repo, monkeypatch):
    rec = Recorder({"A": _rows(("2026-01-02", 100.0))})  # B는 pykrx 미수신
    yf_calls = []

    def fake_yf(codes, since, until):
        yf_calls.append((tuple(codes), since, until))
        return {"B": _rows(("2026-01-02", 50.0))}

    monkeypatch.setattr(market, "fetch_prices_pykrx", rec)
    monkeypatch.setattr(market, "fetch_prices_yf", fake_yf)

    out = market.get_prices_cached(["A", "B"], "2026-01-01", "2026-01-02")
    assert yf_calls == [(("B",), "2026-01-01", "2026-01-02")]
    assert out["B"] == _rows(("2026-01-02", 50.0))


def test_merge_rows_dedupes_and_sorts():
    cached = _rows(("2026-01-05", 100.0), ("2026-01-02", 99.0))
    fetched = _rows(("2026-01-05", 555.0), ("2026-01-06", 101.0))
    merged = market._merge_rows(cached, fetched)
    assert [r["date"] for r in merged] == ["2026-01-02", "2026-01-05", "2026-01-06"]
    assert merged[1]["close"] == 100.0  # 중복 날짜는 캐시 우선


def test_kospi_cache_incremental(tmp_repo, monkeypatch):
    _write_cache({"_KOSPI": [{"date": "2026-01-02", "value": 8000.0}],
                  "_meta": {"since": "2026-01-01"}})
    calls = []

    def fake_kospi(since, until):
        calls.append((since, until))
        return [{"date": "2026-01-05", "value": 8100.0}]

    monkeypatch.setattr(market, "fetch_kospi", fake_kospi)
    out = market.get_kospi_cached("2026-01-01", "2026-01-05")

    assert calls == [("2026-01-03", "2026-01-05")]  # 캐시 마지막+1일부터
    assert out == [{"date": "2026-01-02", "value": 8000.0}, {"date": "2026-01-05", "value": 8100.0}]
    assert _read_cache()["_KOSPI"] == out


def test_kospi_cache_full_when_empty(tmp_repo, monkeypatch):
    calls = []

    def fake_kospi(since, until):
        calls.append((since, until))
        return [{"date": "2026-01-02", "value": 8000.0}]

    monkeypatch.setattr(market, "fetch_kospi", fake_kospi)
    out = market.get_kospi_cached("2026-01-01", "2026-01-02")
    assert calls == [("2026-01-01", "2026-01-02")]
    assert _read_cache()["_KOSPI"] == out
