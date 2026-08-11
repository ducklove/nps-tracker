"""기금운용본부 월간 공시 수집 — 「자산군별 포트폴리오 운용 현황 및 수익률」 첨부 xlsx.

공표 원본이라 파생 소스보다 최신월이 빠르다(2026-08 기준: 이 게시판 2026-05, data.go.kr
2026-02, KOSIS 2024-12에서 정지). 목록(cat=MON) → 상세(tmpltdataSn) → 첨부 xlsx 3단계이고
모두 GET·무인증. 게시글은 월 1건이라 새 공표월만 받는다(known_periods로 스킵).

xlsx는 openpyxl 없이 표준 라이브러리로 읽는다(zip + sheet XML 2개만 필요).
"""
from __future__ import annotations

import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile

from .. import config
from ..http import _download

logger = logging.getLogger("nps")

_XL_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_BILLION = 1_000_000_000  # 십억원 → 원
# 첫 표(자산군별 운용 현황)의 끝. 아래 「자산군별 수익률」 표에도 같은 자산군명이 나오므로
# 여기서 끊지 않으면 평가액 자리에 수익률(%)이 들어온다.
_XLSX_SECTION_END = "자산군별 수익률"
_XLSX_ASOF_RE = re.compile(r"(\d{4})\.\s*(\d{1,2})월\s*말\s*기준")


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _cell_col(ref: str) -> str:
    """셀 참조("B12") → 열 문자("B")."""
    m = re.match(r"([A-Z]+)", ref or "")
    return m.group(1) if m else ""


def _sheet_rows(payload: bytes) -> list[dict[str, str]]:
    """xlsx 첫 시트 → 행별 {열문자: 값} 목록. 값은 공유문자열·인라인문자열·숫자 모두 문자열로."""
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        names = set(z.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            shared = ["".join(t.text or "" for t in si.iter(_XL_NS + "t"))
                      for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
        sheet_name = next((n for n in sorted(names) if n.startswith("xl/worksheets/sheet")), None)
        if not sheet_name:
            return []
        sheet = ET.fromstring(z.read(sheet_name))
    rows: list[dict[str, str]] = []
    for row in sheet.iter(_XL_NS + "row"):
        cells: dict[str, str] = {}
        for c in row.iter(_XL_NS + "c"):
            if c.get("t") == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(_XL_NS + "t"))
            else:
                v = c.find(_XL_NS + "v")
                if v is None or v.text is None:
                    continue
                text = shared[int(v.text)] if c.get("t") == "s" and int(v.text) < len(shared) else v.text
            cells[_cell_col(c.get("r", ""))] = text
        if cells:
            rows.append(cells)
    return rows


def _parse_fund_xlsx(payload: bytes) -> tuple[str | None, dict[str, int]]:
    """첨부 xlsx → (기준월, {자산군키: 원}).

    A열=구분(들여쓰기 공백 포함), B열='현황(말잔)'=그 달 말 평가액(십억원). 파일이 스스로
    "2026.5월 말 기준"을 밝히므로 기준월도 함께 돌려주고, 호출부가 목록 제목과 대조한다.
    """
    as_of: str | None = None
    values: dict[str, int] = {}
    for cells in _sheet_rows(payload):
        label = (cells.get("A") or "").strip()
        if as_of is None:
            m = _XLSX_ASOF_RE.search(" ".join(cells.values()))
            if m:
                as_of = f"{m.group(1)}-{int(m.group(2)):02d}"
        if label.startswith(_XLSX_SECTION_END):
            break  # 운용 현황 표 끝 — 이후는 수익률(%) 표
        key = config._NPS_FUND_ROW_MAP.get(label)
        if not key or key in values:  # 첫 등장만 채택
            continue
        try:
            amount = float(cells.get("B") or "")
        except ValueError:
            continue
        if amount > 0:
            values[key] = round(amount * _BILLION)
    return as_of, values


def _parse_list(html: str) -> list[tuple[str, str]]:
    """월간 공시 목록 HTML → [(기준월, 게시글 일련번호)] (최신순). 「조성·지출·적립」 등은 제외."""
    out: list[tuple[str, str]] = []
    for tr in re.findall(r"<tr[\s\S]*?</tr>", html):
        sn = config._NPS_FUND_DETAIL_SN_RE.search(tr)
        title = config._NPS_FUND_TITLE_RE.search(_strip_tags(tr))
        if sn and title:
            out.append((f"{title.group(1)}-{int(title.group(2)):02d}", sn.group(1)))
    return out


def _fetch_month(sn: str) -> tuple[str | None, dict[str, int]]:
    """상세 페이지에서 xlsx 첨부를 찾아 내려받아 파싱한다."""
    detail = _download(config.NPS_FUND_DETAIL_URL.format(sn=sn), timeout=20).decode("utf-8", "replace")
    files = config._NPS_FUND_FILE_RE.findall(detail)
    if not files:
        logger.warning("기금운용본부 공시(sn=%s) 첨부 없음", sn)
        return None, {}
    # 첨부 순서는 xlsx(1) → 설명 PDF(2). 순서가 바뀌어도 되도록 xlsx로 파싱되는 첫 파일을 쓴다.
    for file_id, file_sn in files:
        payload = _download(config.NPS_FUND_FILE_URL.format(file_id=file_id, file_sn=file_sn),
                            referer=config.NPS_FUND_DETAIL_URL.format(sn=sn), timeout=30)
        if not payload.startswith(b"PK"):  # zip(xlsx)이 아니면 PDF 등 — 건너뜀
            continue
        try:
            return _parse_fund_xlsx(payload)
        except (zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
            logger.warning("기금운용본부 첨부 파싱 실패(sn=%s, %s): %s", sn, file_id, exc)
    return None, {}


def fetch_nps_fund_monthly(known_periods: set[str] | None = None,
                           max_fetch: int | None = None) -> list[dict] | None:
    """기금운용본부 월간 공시에서 아직 없는 공표월의 자산군별 평가액을 수집한다.

    known_periods에 든 월은 이미 확정값이 있으므로 건너뛴다(정상 운영 시 월 1건만 새로 받음).
    한 배치의 다운로드는 max_fetch(기본 config.NPS_FUND_MAX_FETCH)로 제한한다.
    """
    known = known_periods or set()
    limit = config.NPS_FUND_MAX_FETCH if max_fetch is None else max_fetch
    try:
        html = _download(config.NPS_FUND_LIST_URL, timeout=20).decode("utf-8", "replace")
    except Exception as exc:
        logger.warning("기금운용본부 월간 공시 목록 수집 실패: %s", exc)
        return None
    listed = _parse_list(html)
    if not listed:
        logger.warning("기금운용본부 월간 공시 목록에서 자산군별 공시 항목 미발견")
        return None
    pending = [(p, sn) for p, sn in listed if p not in known][:limit]
    if not pending:
        logger.info("기금운용본부 월간 공시 최신 %s — 새 공표월 없음", listed[0][0])
        return None
    out: list[dict] = []
    for period, sn in pending:
        try:
            as_of, values = _fetch_month(sn)
        except Exception as exc:
            logger.warning("기금운용본부 공시(%s, sn=%s) 수집 실패: %s", period, sn, exc)
            continue
        if len(values) < len(config._NPS_FUND_ROW_MAP):
            logger.warning("기금운용본부 공시(%s) 자산군 부족(%d/%d) → 생략",
                           period, len(values), len(config._NPS_FUND_ROW_MAP))
            continue
        if as_of and as_of != period:  # 제목과 파일 기준월 불일치 = 첨부 교체 사고 → 파일 기준월을 믿지 않는다
            logger.warning("기금운용본부 공시 기준월 불일치(제목 %s ≠ 파일 %s) → 생략", period, as_of)
            continue
        out.append({"period": period, "source": "npsfund", **values})
    if out:
        logger.info("기금운용본부 월간 공시 %d개월(%s)", len(out), ", ".join(r["period"] for r in out))
    return out or None
