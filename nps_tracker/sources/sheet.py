"""Google Sheet 수집 — 사용자 공표 월별 금융부문(억원). 공표 확정값의 단일 출처."""
from __future__ import annotations

import csv
import io
import logging
import re

from .. import config
from ..http import _download
from ..io_utils import _pi

logger = logging.getLogger("nps")


def _parse_sheet_period(s: str) -> str | None:
    m = re.match(r"\s*(\d{4})\s*[.\-/]\s*(\d{1,2})", str(s or ""))
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else None


def fetch_sheet_fund() -> list[dict] | None:
    """Google Sheet(공표 월별 금융부문, 억원) → 부문별 시계열(원). 공개 링크 CSV export.

    헤더: 기준월/국내채권/해외채권/국내주식/해외주식/대체투자/단기자금. 비공개면 HTML이 와서 None.
    """
    try:
        raw = _download(config.GOOGLE_SHEET_CSV_URL, timeout=30)
    except Exception as exc:
        logger.warning("시트 수집 실패: %s", exc)
        return None
    text = raw.decode("utf-8", "replace")
    if "<html" in text[:300].lower():
        logger.warning("시트가 비공개(HTML 응답) — 공유를 '링크가 있는 모든 사용자 보기'로 설정 필요")
        return None
    rows = list(csv.reader(io.StringIO(text)))
    hidx = next((i for i, r in enumerate(rows) if r and r[0].strip() == "기준월"), None)
    if hidx is None:
        logger.warning("시트 헤더(기준월) 미발견")
        return None
    header = [h.strip() for h in rows[hidx]]
    idx = {config.SHEET_COL_MAP[h]: i for i, h in enumerate(header) if h in config.SHEET_COL_MAP}
    if len(idx) < len(config.SHEET_COL_MAP):
        logger.warning("시트 컬럼 부족: %s", header)
        return None
    WON = 100_000_000  # 억원 → 원
    out: list[dict] = []
    for r in rows[hidx + 1:]:
        if not r or not r[0].strip():
            continue
        period = _parse_sheet_period(r[0])
        if not period:
            continue
        rec = {"period": period, "source": "sheet"}
        ok = True
        for key, i in idx.items():
            v = _pi(r[i]) if i < len(r) else None
            if v is None:
                ok = False
                break
            rec[key] = v * WON
        if ok:
            out.append(rec)
    return out or None
