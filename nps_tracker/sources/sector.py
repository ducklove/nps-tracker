"""업종분류(F-7) — 종목코드 → 업종명 매핑 + 섹터별 집계.

1순위 KRX 「업종분류현황」(pykrx): KRX 표준 업종(전기전자·서비스업 등 시장별 ~20개).
  단, data.krx.co.kr 이 화면은 로그인을 요구한다 — KRX_ID/KRX_PW 환경변수(데이터포털
  계정)가 있을 때만 성공하고, 없으면 로그인 페이지가 와서 빈 결과가 된다.
2순위 KIND 상장법인목록(로그인 불필요): 표준산업분류(KSIC) 업종명, 전 상장사 ~2,700개.
  GitHub Actions에서도 전체 목록(~1.2MB)이 온다. 2026-08~10 Actions 로그의 「0종목 파싱」은
  차단이 아니라 열 순서 변경(시장구분 열 추가)을 파서가 따라가지 못한 결과였다 — 지금은
  머리글 이름으로 열을 찾는다. 그래도 실패할 수 있어 시도만 하고 실패를 허용한다.
3순위 DART 기업개황(company.json): induty_code(KSIC) 앞 2자리 → 중분류명(config.KSIC_DIVISIONS).
  DART는 Actions에서 검증된 경로이고 corp_code 매핑 캐시를 재사용한다. 평가액 상위
  SECTOR_DART_MAX 종목만 조회(캐시 만료 주기에만 호출되므로 일배치 부담 없음).

우선주는 목록에 없으므로 조회 시 보통주 코드(끝자리 0)로 폴백 매칭한다(sector_for).
결과는 data/sector_cache.json에 캐시(30일 경과 시 재수집, 실패 시 낡은 캐시 폴백 —
DART corpCode와 같은 패턴). 업종 구성은 거의 변하지 않으므로 일배치마다 재수집하지 않는다.
캐시에는 형식 버전(_CACHE_VERSION)을 함께 적는다. 수집기 결함을 고칠 때 버전을 올리면
다음 배치가 30일 만료를 기다리지 않고 한 번 재수집한다(재수집 실패 시 기존 캐시 폴백).
"""
from __future__ import annotations

import html as html_lib
import logging
import re
from datetime import date, timedelta

from .. import config
from ..http import _download
from ..io_utils import _read_json, _write_json, _yyyymmdd
from .dart import _dart_key, _fetch_dart_json_many, load_dart_corp_map

logger = logging.getLogger("nps")

_MARKETS = ("KOSPI", "KOSDAQ")
_LOOKBACK_DAYS = 7  # 조회일이 휴장 등으로 비면 직전 영업일을 찾아 거슬러 가는 한도

# 업종 캐시 형식 버전. 2: KIND 머리글 기반 파서(2026-11) — 그 전 캐시는 KIND 0종목 파싱 탓에
# DART 상위 400종목뿐이라 버전이 다르면 만료 전이라도 한 번 재수집한다.
_CACHE_VERSION = 2

# KIND 상장법인목록 다운로드(EUC-KR HTML 테이블, searchType=13=전체) — 로그인 불필요
KIND_CORPLIST_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
# 응답이 잘렸거나 형식이 바뀌어 일부만 읽힌 결과를 30일 캐시에 굳히지 않기 위한 하한(정상 ~2,700사)
_KIND_MIN_COMPANIES = 1000
_KIND_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_KIND_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
# 종목코드 6자리. 최근 신규 상장 코드는 영문을 섞는다(예: 0222E0, 2026-11 목록 75종목) — 첫 자리는 숫자.
_KIND_CODE_RE = re.compile(r"[0-9][0-9A-Z]{5}")


def _fetch_krx_sector_map(snap_date: str) -> dict[str, str]:
    """KRX 업종분류현황 → {종목코드(6): 업종명}. 로그인 실패 등으로 비면 빈 dict."""
    try:
        from pykrx import stock
    except Exception as exc:
        logger.warning("pykrx 임포트 실패(KRX 업종 생략): %s", exc)
        return {}
    out: dict[str, str] = {}
    base = date.fromisoformat(snap_date)
    for market in _MARKETS:
        for back in range(_LOOKBACK_DAYS):
            day = _yyyymmdd((base - timedelta(days=back)).isoformat())
            try:
                df = stock.get_market_sector_classifications(day, market)
            except Exception:
                continue
            if df is None or not len(df):
                continue
            # pykrx는 종목코드를 인덱스로 두지만, 버전에 따라 컬럼일 수도 있어 둘 다 흡수
            codes = df["종목코드"] if "종목코드" in df.columns else df.index
            for code, sec in zip(codes, df["업종명"]):
                code, sec = str(code).strip(), str(sec).strip()
                if len(code) == 6 and sec:
                    out.setdefault(code, sec)
            break
    return out


def _kind_cells(row: str) -> list[str]:
    """<tr> 안의 <th>/<td> 칸 → 태그·엔티티·연속 공백을 정리한 텍스트 목록."""
    return [_SPACE_RE.sub(" ", html_lib.unescape(_TAG_RE.sub("", c))).strip()
            for c in _KIND_CELL_RE.findall(row)]


def _parse_kind_corplist(html: str) -> dict[str, str]:
    """KIND 상장법인목록 HTML 테이블 → {보통주 종목코드(6): KSIC 업종명}.

    열 순서가 바뀐 적이 있다(예전: 회사명·종목코드·업종…, 2026-11 확인: 회사명·시장구분·
    종목코드·업종…). 그래서 「종목코드」「업종」 머리글이 있는 첫 행에서 열 위치를 찾고,
    그 아래 행만 읽는다. 머리글을 못 찾으면 빈 dict(형식 변경 — 호출부가 경고·폴백).
    """
    out: dict[str, str] = {}
    columns: tuple[int, int] | None = None
    for row in _KIND_ROW_RE.findall(html or ""):
        cells = _kind_cells(row)
        if columns is None:
            if "종목코드" in cells and "업종" in cells:
                columns = (cells.index("종목코드"), cells.index("업종"))
            continue
        code_i, sector_i = columns
        if len(cells) <= max(code_i, sector_i):
            continue
        code, name = cells[code_i].upper(), cells[sector_i]
        if _KIND_CODE_RE.fullmatch(code) and name:
            out.setdefault(code, name)
    return out


def _fetch_kind_sector_map() -> dict[str, str]:
    """KIND 상장법인목록(익명) → {종목코드: 업종명}. 실패·건수 미달 시 빈 dict."""
    try:
        payload = _download(KIND_CORPLIST_URL, referer="https://kind.krx.co.kr/", timeout=60)
    except Exception as exc:
        logger.warning("KIND 상장법인목록 수집 실패: %s", exc)
        return {}
    # EUC-KR의 상위 집합인 CP949로 읽어 일부 회사명의 확장 한글도 살린다.
    out = _parse_kind_corplist(payload.decode("cp949", "replace"))
    if len(out) < _KIND_MIN_COMPANIES:
        # 응답은 왔는데 행을 못 읽음 = 형식 변경 의심. INFO로 묻히면 DART 폴백에 가려 몇 달 모른다.
        logger.warning("KIND 상장법인목록: %dB 수신, %d종목 파싱(하한 %d 미만) — 형식 변경 의심, 폴백",
                       len(payload), len(out), _KIND_MIN_COMPANIES)
        return {}
    logger.info("KIND 상장법인목록: %dB 수신, %d종목 파싱", len(payload), len(out))
    return out


def _fetch_dart_sector_map(codes_by_value: list[str]) -> dict[str, str]:
    """DART 기업개황 induty_code → KSIC 중분류명. 키 없음·실패 시 빈 dict.

    호출량을 평가액 상위 SECTOR_DART_MAX 종목으로 제한한다(가치 커버리지 98%+).
    캐시 만료(30일) 시에만 실행되며, 대량보유와 같은 병렬 헬퍼로 400종목 ≈ 35초.
    """
    key = _dart_key()
    if not key or not codes_by_value:
        return {}
    try:
        corp_map = load_dart_corp_map(key)
    except Exception as exc:
        logger.warning("DART corpCode 매핑 실패(섹터 생략): %s", exc)
        return {}
    targets = []
    for code in codes_by_value[:config.SECTOR_DART_MAX]:
        corp = corp_map.get(code) or (corp_map.get(code[:5] + "0") if len(code) == 6 else None)
        if corp:
            targets.append((code, corp))
    if not targets:
        return {}
    responses = _fetch_dart_json_many(
        targets,
        lambda corp: config.DART_COMPANY_URL.format(key=key, corp_code=corp),
        abort_label="섹터(기업개황)", download=_download)
    out: dict[str, str] = {}
    for code, res in responses.items():
        div = re.sub(r"\D", "", str(res.get("induty_code") or ""))[:2]
        name = config.KSIC_DIVISIONS.get(div)
        if name:
            out[code] = name
    return out


def _fetch_sector_map(snap_date: str, codes_by_value: list[str] | None = None) -> dict[str, str]:
    """KRX 업종분류(로그인 시) → KIND 산업분류(익명) → DART 기업개황(KSIC) 순으로 시도."""
    krx = _fetch_krx_sector_map(snap_date)
    if krx:
        logger.info("KRX 업종분류 수신: %d종목", len(krx))
        return krx
    kind = _fetch_kind_sector_map()
    if kind:
        logger.info("KIND 산업분류 사용(KRX 업종 대신): %d종목", len(kind))
        return kind
    dart = _fetch_dart_sector_map(codes_by_value or [])
    if dart:
        logger.info("DART 기업개황 KSIC 업종 사용(KRX·KIND 대신): %d종목", len(dart))
    return dart


def sector_for(code: str, smap: dict[str, str]) -> str | None:
    """종목코드의 업종. 우선주(끝자리≠0 등)는 보통주 코드(앞 5자리+'0')로 폴백."""
    sec = smap.get(code)
    if sec:
        return sec
    if len(code) == 6 and code[5] != "0":
        return smap.get(code[:5] + "0")
    return None


def load_sector_map(snap_date: str, codes_by_value: list[str] | None = None) -> dict[str, str]:
    """업종 매핑. 신선한 캐시 → 재수집 → (실패 시) 낡은 캐시 순. 전부 실패하면 빈 dict.

    형식 버전이 다른 캐시(버전 없는 옛 캐시 포함)는 날짜가 신선해도 재수집 대상이다.
    """
    cached = _read_json(config.SECTOR_CACHE) or {}
    cmap = cached.get("map") or {}
    if cmap:
        try:
            age = (date.today() - date.fromisoformat(cached.get("fetched", ""))).days
        except ValueError:
            age = 10**6
        if age <= config.SECTOR_CACHE_MAX_AGE_DAYS:
            if cached.get("version") == _CACHE_VERSION:
                return cmap
            logger.info("업종 캐시 형식 버전 %s → %s: 만료 전이지만 재수집",
                        cached.get("version"), _CACHE_VERSION)
    fresh = _fetch_sector_map(snap_date, codes_by_value)
    if fresh:
        _write_json(config.SECTOR_CACHE,
                    {"version": _CACHE_VERSION, "fetched": date.today().isoformat(), "map": fresh})
        logger.info("업종 매핑 갱신: %d종목", len(fresh))
        return fresh
    if cmap:
        logger.warning("업종 재수집 실패 → 낡은 캐시 사용(%d종목)", len(cmap))
    return cmap


def aggregate_sectors(evaluated: list[dict]) -> list[dict]:
    """평가 완료 보유종목(h["sector"] 부착됨)을 섹터별 비중·등락·기여도로 집계.

    섹터 일간 등락은 전일 평가액(prev = mv/(1+chg/100)) 가중, 기여도는 포트폴리오
    전일 합계 대비(프런트 F-1 기여도와 같은 산식). sector가 하나도 없으면 빈 리스트.
    """
    if not any(h.get("sector") for h in evaluated):
        return []
    total_mv = sum(h.get("market_value") or 0 for h in evaluated)
    if not total_mv:
        return []
    total_prev = 0.0
    groups: dict[str, dict] = {}
    for h in evaluated:
        mv = h.get("market_value") or 0
        if mv <= 0:
            continue
        g = groups.setdefault(h.get("sector") or config.SECTOR_UNMAPPED_LABEL,
                              {"value": 0, "mv_chg": 0, "prev": 0.0, "count": 0})
        g["value"] += mv
        g["count"] += 1
        chg = h.get("change_pct")
        # 등락 집계는 change_pct 있는 종목만으로 분자·분모를 맞춘다(없는 종목은 비중에만 기여)
        if chg is not None and (1 + chg / 100) > 0:
            prev = mv / (1 + chg / 100)
            g["mv_chg"] += mv
            g["prev"] += prev
            total_prev += prev
    out = []
    for name, g in groups.items():
        change = (g["mv_chg"] - g["prev"]) / g["prev"] * 100 if g["prev"] > 0 else None
        # 기여도 분모는 등락 산출 가능 종목의 전일 합 — 섹터 합산 시 포트폴리오 일간 변동과 일치
        contrib = (g["mv_chg"] - g["prev"]) / total_prev * 100 if (total_prev > 0 and g["prev"] > 0) else None
        out.append({
            "name": name,
            "value": g["value"],
            "weightPct": round(g["value"] / total_mv * 100, 2),
            "changePct": round(change, 2) if change is not None else None,
            "contribPct": round(contrib, 3) if contrib is not None else None,
            "count": g["count"],
        })
    out.sort(key=lambda s: s["value"], reverse=True)
    return out
