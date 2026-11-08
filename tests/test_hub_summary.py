"""허브용 요약(summary.json/version.json, 생태계 발행 데이터 계약 v1 — X14)과 no-op 규칙(P2).

계약: value-invest docs/ecosystem/data-contract.md §6.7 / config/schemas/summary/nps-tracker.schema.json.
허브 스키마 파일은 이 저장소에 없으므로 필수 키·형식을 여기서 직접 고정한다.
"""
from __future__ import annotations

import json
import math
import os
import re

import pytest

from nps_tracker import config, hub_summary
from nps_tracker import vc_publish as vp
from nps_tracker.publish import write_outputs

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _current(**over):
    cur = {
        "lastUpdated": "2026-09-25 15:48",
        "asOf": "2026-09-23",
        "source": "data.go.kr(2024-12-31)",
        "summary": {"totalValue": 423899242668346, "nav": 3092.31, "count": 3, "todayPct": 1.013697829545854,
                    "mtdPct": 3.9627990237455224, "ytdPct": 71.5428976914875, "asOf": "2026-09-23"},
        "allocation": {"asOf": "2026-09", "estimated": True, "classes": [
            {"key": "domestic_stock", "label": "국내주식", "pct": 26.5},
            {"key": "foreign_stock", "label": "해외주식", "pct": 35.1},
        ]},
        "holdings": [
            {"stock_code": "000660", "stock_name": "SK하이닉스", "weight": 23.490093522980374,
             "market_value": 99574328546000, "change_pct": 1.1956521739130421, "ownership_pct": 7.55,
             "sector": "전자부품·통신장비"},
            {"stock_code": "005930", "stock_name": "삼성전자", "weight": 29.17117322777275,
             "market_value": 123656382390000, "change_pct": 3.2549728752260476, "ownership_pct": 7.26,
             "sector": "전자부품·통신장비"},
            {"stock_code": "0000", "stock_name": "코드 이상", "weight": 50.0, "market_value": 1},
            {"stock_code": "0126Z0", "stock_name": "신규 코드", "weight": None, "market_value": 5,
             "change_pct": float("nan"), "ownership_pct": None, "sector": None},
        ],
    }
    cur.update(over)
    return cur


# ---------- 빌더 ----------

def test_build_summary_data_shape_matches_contract():
    data = hub_summary.build_summary_data(_current())
    assert set(data) == {"lastUpdated", "source", "summary", "allocation", "top",
                         "positionsAsOf", "weights", "ownership", "ownershipChange"}
    assert set(data["summary"]) == {"totalValue", "nav", "count", "todayPct", "mtdPct", "ytdPct", "asOf"}
    assert data["summary"]["asOf"] == "2026-09-23"
    assert data["summary"]["todayPct"] == 1.0137 and data["summary"]["count"] == 3
    # top: 비중 내림차순, 6자리 코드만, 모르는 값은 null(NaN 포함)
    assert [t["code"] for t in data["top"]] == ["005930", "000660", "0126Z0"]
    assert data["top"][0] == {"code": "005930", "name": "삼성전자", "weight": 29.1712,
                              "marketValue": 123656382390000, "changePct": 3.255, "ownershipPct": 7.26,
                              "sector": "전자부품·통신장비"}
    assert data["top"][2]["weight"] is None and data["top"][2]["changePct"] is None
    for t in data["top"]:
        assert re.match(r"^[0-9A-Z]{6}$", t["code"])
        assert {"code", "name", "weight"} <= set(t)


def test_top_is_capped():
    holdings = [{"stock_code": f"{i:06d}", "stock_name": str(i), "weight": float(i), "market_value": i}
                for i in range(40)]
    data = hub_summary.build_summary_data(_current(holdings=holdings))
    assert len(data["top"]) == hub_summary.TOP_N <= 20
    assert data["top"][0]["code"] == "000039"


def test_allocation_carries_targets_and_null_when_missing():
    data = hub_summary.build_summary_data(_current())
    classes = data["allocation"]["classes"]
    assert classes[0] == {"key": "domestic_stock", "label": "국내주식", "pct": 26.5,
                          "target": config.FUND_TARGETS["domestic_stock"]}
    assert data["allocation"]["asOf"] == "2026-09" and data["allocation"]["estimated"] is True
    assert hub_summary.build_summary_data(_current(allocation=None))["allocation"] is None


def test_envelope_validates_and_is_deterministic():
    env = hub_summary.build_summary_envelope(_current())
    vp.validate_envelope(env)
    assert env["tool"] == "nps-tracker" and env["kind"] == "summary" and env["schemaVersion"] == 1
    assert env["asOf"] == "2026-09-23"                         # 데이터 기준일(실행 시각 아님)
    assert env["generatedAt"] == "2026-09-25T15:48:00+09:00"   # lastUpdated 유래 → 결정적
    assert hub_summary.build_summary_envelope(_current()) == env
    assert all(not str(s.get("url", "")).startswith("http://") for s in env["sources"])
    assert len(vp.dumps_compact(env)) < 16 * 1024               # 계약 권장 크기


def test_envelope_requires_data_date():
    cur = _current()
    cur["summary"]["asOf"] = None
    cur["asOf"] = None
    with pytest.raises(vp.EnvelopeError):
        hub_summary.build_summary_envelope(cur)


# ---------- 비중·지분율 맵과 지분율 변화 ----------

def test_position_maps_cover_every_holding_and_skip_unknowns():
    data = hub_summary.build_summary_data(_current())
    assert data["weights"] == {"000660": 23.49, "005930": 29.171}   # 코드 이상·비중 없음 제외, 소수 3자리
    assert data["ownership"] == {"000660": 7.55, "005930": 7.26}
    assert data["positionsAsOf"] == "2024-12-31"                    # 가격 기준일이 아니라 공시 기준일
    assert data["ownershipChange"] is None                          # 인자가 없으면 null

    zero = _current(holdings=[{"stock_code": "005930", "weight": 1.0, "ownership_pct": 0.0}])
    assert hub_summary.build_summary_data(zero)["ownership"] == {}  # 0.0은 CSV 공란 — 공시 값이 아니다
    assert hub_summary.build_summary_data(_current(source=None))["positionsAsOf"] is None


def _write_archive(archive_dir, day, rows):
    holdings = [{"stock_code": code, "stock_name": code, "shares": shares, "ownership_pct": pct}
                for code, shares, pct in rows]
    (archive_dir / f"holdings_{day}.json").write_text(json.dumps({"date": day, "holdings": holdings}), encoding="utf-8")


def test_ownership_change_compares_filed_ownership(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ARCHIVE_DIR", str(tmp_path))
    assert hub_summary.compute_ownership_change() is None  # 아카이브 없음
    _write_archive(tmp_path, "2023-12-31", [("000660", 10, 7.0), ("005930", 10, 7.26), ("000020", 10, 5.0),
                                            ("000040", 10, 0.0)])
    assert hub_summary.compute_ownership_change() is None  # 1개뿐
    _write_archive(tmp_path, "2024-12-31", [("000660", 90, 7.55), ("005930", 10, 7.26), ("000020", 10, 4.5),
                                            ("000040", 10, 3.0), ("000050", 10, 6.0)])
    assert hub_summary.compute_ownership_change() == {
        "from": "2023-12-31", "to": "2024-12-31", "comparable": True,
        # 변화 없는 종목은 빼고, 한쪽 값을 모르는 종목(0.0 공란·신규 편입)은 비교하지 않는다.
        "changes": {"000020": -0.5, "000660": 0.55},
    }


def test_ownership_change_flags_the_same_file_republished_under_a_new_date(tmp_path, monkeypatch):
    """2024-12-31과 2025-12-31 아카이브처럼 지분율이 전부 같고 추정 수량만 다르면 변화를 내지 않는다."""
    monkeypatch.setattr(config, "ARCHIVE_DIR", str(tmp_path))
    rows = [(f"{i:06d}", 100, 5.0 + i / 100) for i in range(1, 101)]
    _write_archive(tmp_path, "2024-12-31", rows)
    _write_archive(tmp_path, "2025-12-31", [(code, shares // 2, pct) for code, shares, pct in rows])
    assert hub_summary.compute_ownership_change() == {
        "from": "2024-12-31", "to": "2025-12-31", "comparable": False, "changes": {},
    }


def test_committed_archives_are_flagged_or_produce_real_changes():
    change = hub_summary.compute_ownership_change()
    assert change is not None and change["from"] < change["to"]
    assert change["comparable"] is bool(change["changes"])


def test_full_position_maps_stay_within_the_size_budget():
    with open(os.path.join(REPO, "current.json"), encoding="utf-8") as f:
        env = hub_summary.build_summary_envelope(json.load(f))
    assert len(vp.dumps_compact(env).encode("utf-8")) < 64 * 1024  # 계약 §9 크기 예산


# ---------- 쓰기(no-op) ----------

def test_publish_unchanged_does_not_rewrite(tmp_path):
    assert hub_summary.publish_summary(_current(), str(tmp_path)) is True
    summary, version = tmp_path / "summary.json", tmp_path / "version.json"
    env = json.loads(summary.read_text(encoding="utf-8"))
    vp.validate_envelope(env)
    ver = json.loads(version.read_text(encoding="utf-8"))
    assert ver["files"] == {"summary.json": env["contentHash"]} and ver["tool"] == "nps-tracker"
    before = (summary.read_bytes(), summary.stat().st_mtime_ns, version.read_bytes(), version.stat().st_mtime_ns)
    # 같은 데이터로 재실행 → 파일을 다시 쓰지 않는다(git diff·커밋·배포 없음)
    assert hub_summary.publish_summary(_current(), str(tmp_path)) is False
    after = (summary.read_bytes(), summary.stat().st_mtime_ns, version.read_bytes(), version.stat().st_mtime_ns)
    assert after == before
    # 내용이 바뀌면 다시 쓴다
    cur = _current()
    cur["summary"]["nav"] = 3100.0
    assert hub_summary.publish_summary(cur, str(tmp_path)) is True
    assert json.loads(summary.read_text(encoding="utf-8"))["data"]["summary"]["nav"] == 3100.0


def test_cli_check_and_write(tmp_path, capsys):
    (tmp_path / "current.json").write_text(json.dumps(_current(), ensure_ascii=False), encoding="utf-8")
    assert hub_summary.main(["--root", str(tmp_path), "--check"]) == 1
    assert hub_summary.main(["--root", str(tmp_path)]) == 0
    assert hub_summary.main(["--root", str(tmp_path), "--check"]) == 0
    assert (tmp_path / "summary.json").exists() and (tmp_path / "version.json").exists()


def test_committed_summary_matches_committed_current():
    """커밋된 summary.json은 커밋된 current.json에서 만든 것과 같아야 한다(오프라인 재생성: python -m nps_tracker.hub_summary)."""
    with open(os.path.join(REPO, "summary.json"), encoding="utf-8") as f:
        env = json.load(f)
    vp.validate_envelope(env)
    with open(os.path.join(REPO, "current.json"), encoding="utf-8") as f:
        expected = hub_summary.build_summary_envelope(json.load(f))
    assert (env["asOf"], env["contentHash"]) == (expected["asOf"], expected["contentHash"])
    with open(os.path.join(REPO, "version.json"), encoding="utf-8") as f:
        assert json.load(f)["files"]["summary.json"] == env["contentHash"]


# ---------- write_outputs 통합: P2 no-op + summary 발행 ----------

HIST = [
    {"date": "2026-06-08", "total_value": 30_600, "nav": 1000.0, "total_count": 2},
    {"date": "2026-06-09", "total_value": 31_000, "nav": 1013.07, "total_count": 2},
]
FUND = {"unit": "won", "asOf": "2026-02", "series": [
    {"period": "2026-02", "domestic_stock": 100, "foreign_stock": 200, "domestic_bond": 50,
     "foreign_bond": 25, "alternative": 60, "short_term": 5, "total": 440}]}


def _holdings(price=200.0):
    return [
        {"stock_code": "005930", "stock_name": "삼성전자", "shares": 100, "ownership_pct": 7.26,
         "price": price, "market_value": int(price * 100), "change_pct": 1.5},
        {"stock_code": "000660", "stock_name": "SK하이닉스", "shares": 10, "ownership_pct": 6.4,
         "price": 1100.0, "market_value": 11_000, "change_pct": -0.5},
    ]


def _write(monkeypatch, stamp, price=200.0):
    from nps_tracker import publish
    monkeypatch.setattr(publish, "kst_stamp", lambda fmt: stamp)
    return write_outputs("2026-06-09", "seed(2024-12-31)", _holdings(price), 31_000, 1013.07,
                         1.2, 3.4, 5.6, HIST, [{"date": "2026-06-09", "value": 8000.0}], fund_portfolio=FUND)


def _snapshot(root):
    names = ["data.js", "data.json", "current.json", "summary.json", "version.json"]
    return {n: ((root / n).read_bytes(), (root / n).stat().st_mtime_ns) for n in names}


def test_write_outputs_noop_keeps_files_and_last_updated(tmp_repo, monkeypatch):
    assert _write(monkeypatch, "2026-06-09 15:50") is True
    first = _snapshot(tmp_repo)
    env = json.loads((tmp_repo / "summary.json").read_text(encoding="utf-8"))
    vp.validate_envelope(env)
    assert env["asOf"] == "2026-06-09" and env["data"]["lastUpdated"] == "2026-06-09 15:50"
    assert env["data"]["allocation"]["classes"][0]["key"] == "domestic_stock"

    # 같은 데이터, 다른 실행 시각 → 아무 파일도 다시 쓰지 않고 lastUpdated 유지
    assert _write(monkeypatch, "2026-06-10 15:50") is False
    assert _snapshot(tmp_repo) == first
    data = json.loads((tmp_repo / "data.json").read_text(encoding="utf-8"))
    assert data["lastUpdated"] == "2026-06-09 15:50"


def test_write_outputs_content_change_rewrites(tmp_repo, monkeypatch):
    _write(monkeypatch, "2026-06-09 15:50")
    assert _write(monkeypatch, "2026-06-10 15:50", price=210.0) is True
    data = json.loads((tmp_repo / "data.json").read_text(encoding="utf-8"))
    cur = json.loads((tmp_repo / "current.json").read_text(encoding="utf-8"))
    env = json.loads((tmp_repo / "summary.json").read_text(encoding="utf-8"))
    assert data["lastUpdated"] == cur["lastUpdated"] == env["data"]["lastUpdated"] == "2026-06-10 15:50"
    assert env["data"]["top"][0]["marketValue"] == 21_000


def test_write_outputs_restores_missing_data_js(tmp_repo, monkeypatch):
    _write(monkeypatch, "2026-06-09 15:50")
    (tmp_repo / "data.js").unlink()
    assert _write(monkeypatch, "2026-06-10 15:50") is True
    assert (tmp_repo / "data.js").exists()


def test_write_outputs_bad_summary_does_not_block_publish(tmp_repo, monkeypatch, caplog):
    from nps_tracker import publish

    def boom(current, root=None):
        raise vp.EnvelopeError("bad")
    monkeypatch.setattr(publish, "publish_summary", boom)
    assert _write(monkeypatch, "2026-06-09 15:50") is True
    assert (tmp_repo / "data.json").exists() and not (tmp_repo / "summary.json").exists()
    assert any("summary.json 발행 생략" in r.message for r in caplog.records)


def test_num_rejects_non_finite():
    assert hub_summary._num(float("inf")) is None
    assert hub_summary._num("x") is None
    assert hub_summary._num(True) is None
    assert hub_summary._num(1.23456, 2) == 1.23
    assert not math.isnan(hub_summary._num(0.0))
