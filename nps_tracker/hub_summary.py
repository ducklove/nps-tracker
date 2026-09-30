"""허브(Value Compass)용 요약 발행 — summary.json + version.json (생태계 발행 데이터 계약 v1, X14).

허브는 지금 인사이트 카드에 요약·자산배분·상위 종목만 쓰려고 313 KB current.json 전체를 받는다.
이 모듈은 그 필드만 담은 ~2 KB envelope(summary.json)과 변경 감지용 version.json을 저장소 루트
(= Pages 루트)에 발행한다. 기존 current.json/data.json은 그대로 발행된다(추가만).

- 계약: value-invest docs/ecosystem/data-contract.md §6.7, 스키마 config/schemas/summary/nps-tracker.schema.json
- envelope 헬퍼: nps_tracker/vc_publish.py(허브 정본을 sync-ecosystem.mjs가 벤더링 — 직접 수정 금지)
- asOf = 가격 기준일(summary.asOf, 데이터 날짜). 실행 시각을 넣지 않는다(no-op 비교 대상).
- generatedAt = 발행물 lastUpdated(KST) — 같은 입력이면 같은 파일(결정적). 형식이 다르면 헬퍼 기본값(now).
- write_if_changed: 내용(contentHash)·asOf가 같으면 파일을 다시 쓰지 않아 git diff가 생기지 않는다.

오프라인 재생성(네트워크 없음, 커밋된 current.json 기준):
    python -m nps_tracker.hub_summary            # summary.json/version.json 갱신(변경 시에만)
    python -m nps_tracker.hub_summary --check    # 변경이 필요하면 exit 1(쓰지 않음)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

from . import config
from . import vc_publish as vp

TOOL_ID = "nps-tracker"
SUMMARY_FILE = "summary.json"
VERSION_FILE = "version.json"
TOP_N = 10  # 계약 권장 10(스키마 최대 20)

# 원천 — envelope sources(해시 비포함). 비밀값·내부 주소 금지.
SOURCES = [
    {"id": "data-go-kr", "name": "공공데이터포털 국민연금 보유종목", "url": "https://www.data.go.kr/"},
    {"id": "opendart", "name": "OpenDART", "url": "https://opendart.fss.or.kr/"},
    {"id": "kis", "name": "한국투자증권 Open API"},
    {"id": "nps-fund", "name": "국민연금 기금운용본부 기금 공시", "url": "https://fund.nps.or.kr/"},
]

_CODE_RE = re.compile(r"^[0-9A-Z]{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::(\d{2}))?$")


def _num(v, digits: int | None = None):
    """숫자 정규화: 모르는 값(None·NaN·Inf·비숫자)은 null — 0으로 채우지 않는다(계약 §2)."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    if isinstance(v, int):
        return v
    return round(f, digits) if digits is not None else f


def _int_or_none(v):
    n = _num(v)
    return int(n) if n is not None else None


def _allocation(alloc: dict | None) -> dict | None:
    """current.json allocation → 계약 모양. 목표비중(config.FUND_TARGETS)이 있으면 target으로 싣는다."""
    if not isinstance(alloc, dict):
        return None
    classes = []
    for c in alloc.get("classes") or []:
        if not isinstance(c, dict) or not c.get("key") or not c.get("label"):
            continue
        item = {"key": str(c["key"]), "label": str(c["label"]), "pct": _num(c.get("pct"), 2)}
        target = config.FUND_TARGETS.get(item["key"])
        if target is not None:
            item["target"] = _num(target, 2)
        classes.append(item)
    if not classes:
        return None
    return {
        "asOf": alloc.get("asOf"),
        "estimated": bool(alloc.get("estimated")),
        "classes": classes,
    }


def _top(holdings: list[dict] | None, n: int = TOP_N) -> list[dict]:
    """비중 내림차순 상위 n — 코드 형식(6자리)이 아닌 행은 제외."""
    rows = [h for h in holdings or [] if isinstance(h, dict) and _CODE_RE.match(str(h.get("stock_code") or ""))]
    rows.sort(key=lambda h: (_num(h.get("weight")) is None, -(_num(h.get("weight")) or 0),
                             -(_num(h.get("market_value")) or 0), str(h.get("stock_code"))))
    return [{
        "code": str(h["stock_code"]),
        "name": h.get("stock_name"),
        "weight": _num(h.get("weight"), 4),
        "marketValue": _num(h.get("market_value")),
        "changePct": _num(h.get("change_pct"), 4),
        "ownershipPct": _num(h.get("ownership_pct"), 4),
        "sector": h.get("sector"),
    } for h in rows[:n]]


def build_summary_data(current: dict) -> dict:
    """current.json(모양의 dict) → summary.json의 data payload(계약 §6.7)."""
    s = current.get("summary") or {}
    as_of = s.get("asOf") or current.get("asOf")
    return {
        "lastUpdated": current.get("lastUpdated"),
        "source": current.get("source"),
        "summary": {
            "totalValue": _num(s.get("totalValue")),
            "nav": _num(s.get("nav"), 2),
            "count": _int_or_none(s.get("count")),
            "todayPct": _num(s.get("todayPct"), 4),
            "mtdPct": _num(s.get("mtdPct"), 4),
            "ytdPct": _num(s.get("ytdPct"), 4),
            "asOf": as_of if isinstance(as_of, str) and _DATE_RE.match(as_of) else None,
        },
        "allocation": _allocation(current.get("allocation")),
        "top": _top(current.get("holdings")),
    }


def _generated_at(last_updated) -> str | None:
    """lastUpdated('YYYY-MM-DD HH:MM', KST) → envelope generatedAt. 해석 불가면 None(헬퍼가 now 사용)."""
    m = _STAMP_RE.match(str(last_updated or "").strip())
    if not m:
        return None
    return f"{m.group(1)}T{m.group(2)}:{m.group(3) or '00'}+09:00"


def build_summary_envelope(current: dict) -> dict:
    data = build_summary_data(current)
    as_of = data["summary"]["asOf"]
    if not as_of:
        raise vp.EnvelopeError("summary.asOf(가격 기준일)가 없어 envelope asOf를 정할 수 없음")
    return vp.build_envelope(TOOL_ID, data, as_of=as_of, sources=SOURCES,
                             generated_at=_generated_at(data["lastUpdated"]))


def publish_summary(current: dict, root: str | None = None) -> bool:
    """summary.json·version.json 발행(no-op 규칙). summary 내용이 바뀌어 다시 썼으면 True."""
    root = root or config.ROOT
    env = build_summary_envelope(current)
    changed = vp.write_if_changed(os.path.join(root, SUMMARY_FILE), env)
    vp.write_version(os.path.join(root, VERSION_FILE), {SUMMARY_FILE: env}, generated_at=env["generatedAt"])
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="커밋된 current.json으로 summary.json/version.json을 오프라인 생성")
    ap.add_argument("--root", default=None, help="저장소 루트(기본: config.ROOT)")
    ap.add_argument("--check", action="store_true", help="쓰지 않고 갱신 필요 여부만 검사(필요하면 exit 1)")
    args = ap.parse_args(argv)
    root = args.root or config.ROOT
    with open(os.path.join(root, "current.json"), encoding="utf-8") as f:
        current = json.load(f)
    if args.check:
        env = build_summary_envelope(current)
        try:
            with open(os.path.join(root, SUMMARY_FILE), encoding="utf-8") as f:
                existing = json.load(f)
        except (OSError, ValueError):
            existing = None
        keys = ("schemaVersion", "tool", "kind", "asOf", "contentHash")  # write_if_changed와 같은 비교
        stale = not isinstance(existing, dict) or any(existing.get(k) != env[k] for k in keys)
        print(f"{SUMMARY_FILE}: {'갱신 필요' if stale else '최신'} ({env['contentHash']})")
        return 1 if stale else 0
    changed = publish_summary(current, root)
    print(f"{SUMMARY_FILE}: {'갱신' if changed else '변경 없음(no-op)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
