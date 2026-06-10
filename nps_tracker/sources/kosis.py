"""KOSIS 「기금운용현황(시가)」 수집 — 월별 부문별 시계열(2012~2024)."""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict

from .. import config
from ..http import _download

logger = logging.getLogger("nps")


def fetch_kosis_fund_monthly() -> list[dict] | None:
    """KOSIS 「기금운용현황(시가)」 월별 부문분해 시계열(2012-01~2024-12, 원 단위).

    DT_32202_B095는 PRD_DE=연도 × C2=월(02~13=1~12월) 구조다. C1(부문) 코드로 자산군을 합성:
      국내주식=주식(A010)-주식해외(A014), 국내채권=채권(A005)-채권해외(A009),
      해외주식=A014, 해외채권=A009, 대체=A015, 단기=A016, 복지·공공=A002+A003, 기타=A017+A018.
    KOSIS_API_KEY 환경변수가 없으면 None(→ data.go.kr/seed 폴백).
    """
    key = os.environ.get("KOSIS_API_KEY", "").strip()
    if not key:
        logger.info("KOSIS_API_KEY 없음 → KOSIS 월별 생략")
        return None
    raw = _download(config.KOSIS_FUND_URL.format(key=key), timeout=40)
    arr = json.loads(raw.decode("utf-8"))
    if not isinstance(arr, list) or not arr:
        return None
    by_period: dict[str, dict] = defaultdict(dict)
    for r in arr:
        c2 = r.get("C2")
        if not c2 or c2 == "01":  # 01=연간 합계행 제외
            continue
        try:
            month = int(c2) - 1
            year = int(r["PRD_DE"])
            val = float(r["DT"])
        except (TypeError, ValueError, KeyError):
            continue
        if 1 <= month <= 12:
            by_period[f"{year}-{month:02d}"][r.get("C1")] = val
    WON = 1_000_000  # 백만원 → 원
    series: list[dict] = []
    for period in sorted(by_period):
        d = by_period[period]

        def g(k):
            return d.get(k, 0) or 0

        total = g("A001")
        if total <= 0:
            continue
        series.append({
            "period": period,
            "total": round(total * WON),
            "domestic_stock": round((g("A010") - g("A014")) * WON),
            "foreign_stock": round(g("A014") * WON),
            "domestic_bond": round((g("A005") - g("A009")) * WON),
            "foreign_bond": round(g("A009") * WON),
            "alternative": round(g("A015") * WON),
            "short_term": round(g("A016") * WON),
            "welfare": round((g("A002") + g("A003")) * WON),
            "etc": round((g("A017") + g("A018")) * WON),
        })
    return series or None
