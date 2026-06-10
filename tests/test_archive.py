"""archive(F-6) — 스냅샷 보존 불변성과 YoY 비교 산출. 전부 오프라인."""
from __future__ import annotations

import json
import os

from nps_tracker import config
from nps_tracker.archive import compute_yoy, ensure_archive, list_archive_dates


def _h(code, name, shares, own=5.0):
    return {"stock_code": code, "stock_name": name, "shares": shares, "ownership_pct": own}


def test_ensure_archive_creates_once(tmp_repo):
    holdings = [_h("005930", "삼성전자", 100)]
    assert ensure_archive(holdings, "2024-12-31") is True
    path = os.path.join(config.ARCHIVE_DIR, "holdings_2024-12-31.json")
    assert os.path.exists(path)
    # 같은 기준일 재호출은 덮어쓰지 않는다(원본 불변) — 내용을 바꿔 호출해도 기존 파일 유지
    assert ensure_archive([_h("005930", "삼성전자", 999_999)], "2024-12-31") is False
    saved = json.load(open(path, encoding="utf-8"))
    assert saved["holdings"][0]["shares"] == 100
    assert list_archive_dates() == ["2024-12-31"]


def test_ensure_archive_skips_empty(tmp_repo):
    assert ensure_archive([], "2024-12-31") is False
    assert ensure_archive([_h("005930", "삼성전자", 100)], "") is False
    assert list_archive_dates() == []


def test_compute_yoy_needs_two_archives(tmp_repo):
    assert compute_yoy() is None
    ensure_archive([_h("005930", "삼성전자", 100)], "2024-12-31")
    assert compute_yoy() is None


def test_compute_yoy_diff_and_ordering(tmp_repo):
    old = [
        _h("005930", "삼성전자", 1000),   # 유지·증가
        _h("000660", "SK하이닉스", 500),  # 유지·감소
        _h("035420", "NAVER", 300),       # 전량 매도
        _h("012345", "저지분", 10, own=0.5),  # 전량 매도(지분 낮음 → removed 정렬 뒤)
        _h("111111", "변화없음", 200),    # 수량 동일 → topChanges 제외
    ]
    new = [
        _h("005930", "삼성전자", 1200),       # +20%
        _h("000660", "SK하이닉스", 400),      # -20%
        _h("111111", "변화없음", 200),
        _h("068270", "셀트리온", 700, own=7.0),  # 신규 편입(가격 있음)
        _h("999999", "신규무가격", 50, own=6.0),  # 신규 편입(가격 없음 → value None, 뒤로)
    ]
    ensure_archive(old, "2024-12-31")
    ensure_archive(new, "2025-12-31")
    prices = {
        "068270": [{"date": "2025-12-30", "close": 200_000.0}],
        "005930": [{"date": "2025-12-30", "close": 60_000.0}],
        "000660": [{"date": "2025-12-30", "close": 150_000.0}],
    }
    yoy = compute_yoy(prices)
    assert yoy["from"] == "2024-12-31" and yoy["to"] == "2025-12-31"
    assert yoy["addedTotal"] == 2 and yoy["removedTotal"] == 2

    added = yoy["added"]
    assert [a["stock_code"] for a in added] == ["068270", "999999"]  # 평가액 있는 종목 먼저
    assert added[0]["value"] == 700 * 200_000

    removed = yoy["removed"]
    assert [r["stock_code"] for r in removed] == ["035420", "012345"]  # 지분율 내림차순

    changes = {c["stock_code"]: c for c in yoy["topChanges"]}
    assert "111111" not in changes  # 변화 없음 제외
    assert changes["005930"]["change_pct"] == 20.0
    assert changes["000660"]["change_pct"] == -20.0
    # 정렬: 기준일 종가 × |수량변화| — 하이닉스(100주×15만=1500만) > 삼성(200주×6만=1200만)
    assert [c["stock_code"] for c in yoy["topChanges"]] == ["000660", "005930"]


def test_compute_yoy_min_change_filter(tmp_repo, monkeypatch):
    monkeypatch.setattr(config, "YOY_MIN_CHANGE_PCT", 5.0)
    ensure_archive([_h("005930", "삼성전자", 1000)], "2024-12-31")
    ensure_archive([_h("005930", "삼성전자", 1030)], "2025-12-31")  # +3% < 5%
    yoy = compute_yoy()
    assert yoy["topChanges"] == [] and yoy["changedTotal"] == 0
