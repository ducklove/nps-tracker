"""연기금·공제회 비교(F-15) — seed 로드, NPS 라이브 값 대체, 정렬·생략 규칙. 전부 오프라인."""
from __future__ import annotations

from nps_tracker import config
from nps_tracker.fund import get_peer_funds
from nps_tracker.io_utils import _write_json

SEED = {
    "updated": "2026-07-06",
    "note": "테스트",
    "funds": [
        {"key": "nps", "name": "국민연금", "kind": "연금", "asOf": "2025-12",
         "total": 1_458_000_000_000_000, "returnPct": 18.82, "returnYear": 2025,
         "allocation": None, "basis": "적립금(공표)"},
        {"key": "geps", "name": "공무원연금", "kind": "연금", "asOf": "2025-12",
         "total": 12_466_700_000_000, "returnPct": 17.4, "returnYear": 2025,
         "allocation": {"stock": 33.8, "bond": 27.9, "altEtc": 38.3}, "basis": "금융자산"},
        {"key": "broken", "name": "규모없음", "total": None},  # total 없으면 제외
    ],
}

FP = {"series": [
    {"period": "2026-06", "estimated": True, "total": 1_300_000_000_000_000,
     "domestic_stock": 300e12, "foreign_stock": 400e12,
     "domestic_bond": 280e12, "foreign_bond": 70e12,
     "alternative": 200e12, "short_term": 50e12},
]}


def test_seed_missing_returns_none(tmp_repo):
    assert get_peer_funds(None) is None


def test_nps_live_fill_and_sort(tmp_repo):
    _write_json(config.SEED_PEER_FUNDS, SEED)
    out = get_peer_funds(FP)
    assert out["updated"] == "2026-07-06"
    names = [f["name"] for f in out["funds"]]
    assert names == ["국민연금", "공무원연금"]  # total 내림차순, total 없는 항목 제외
    nps = out["funds"][0]
    # 규모·기준시점·배분이 시계열 최신 값으로 대체됨
    assert nps["total"] == 1_300_000_000_000_000
    assert nps["asOf"] == "2026-06"
    assert "추정" in nps["basis"]
    assert nps["allocation"] == {"stock": 53.8, "bond": 26.9, "altEtc": 19.2}
    # 수익률은 seed 값 유지(시계열로는 산출하지 않음)
    assert nps["returnPct"] == 18.82
    # 타 기관은 seed 그대로
    geps = out["funds"][1]
    assert geps["total"] == 12_466_700_000_000
    assert geps["allocation"]["stock"] == 33.8


def test_without_fund_portfolio_keeps_seed_values(tmp_repo):
    _write_json(config.SEED_PEER_FUNDS, SEED)
    out = get_peer_funds(None)
    nps = next(f for f in out["funds"] if f["key"] == "nps")
    assert nps["total"] == 1_458_000_000_000_000  # seed 폴백
    assert nps["asOf"] == "2025-12"
    assert nps["allocation"] is None
