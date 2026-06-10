"""DART OpenAPI 「대량보유 상황보고」(majorstock) — 국민연금 5%↑ 지분 공시를 공시 당일 반영.

FnGuide(동일 공시를 집계하는 사이트의 HTML 스크레이핑)를 공식 API로 대체·보강한다.
cli에서 DART 결과가 FnGuide 위에 덮인다(우선순위: DART > FnGuide > 연말 추정수량).

- 인증키: 환경변수 DART_API_KEY. 없으면 조용히 생략(빈 dict) — KOSIS_API_KEY와 같은 패턴.
- 종목코드(6) → DART 고유번호(8) 매핑은 corpCode.xml(zip)을 받아 data/dart_corp_codes.json에
  캐시한다(30일 경과 시 재수집, 재수집 실패 시 낡은 캐시로 폴백).
- 후보는 연말 공시 지분율 ≥ 4.5% 종목으로 한정한다(현재 ≈290종목 ≈ 일 290회 호출,
  DART 일 한도 20,000건의 1.5%). 대량보유 보고 대상은 5%↑뿐이라 그 미만은 공시 자체가 없다.
  연도 중 신규 5% 진입 종목은 다음 연말 공시 전까지 후보에 안 잡히는 한계가 있으나 FnGuide도 동일하다.
- 보유주식등수(stkqy)는 보고서 '주식등' 기준으로 FnGuide 게재 수치와 같은 의미다.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date

from .. import config
from ..http import _download
from ..io_utils import _pi, _read_json, _write_json

logger = logging.getLogger("nps")

# 키/IP/한도/점검 오류 — 같은 키로 계속 호출해도 소용없으므로 수집을 중단한다.
_ABORT_STATUSES = {"010", "011", "012", "020", "800"}


def _dart_key() -> str:
    return os.environ.get("DART_API_KEY", "").strip()


def _parse_corpcode_zip(payload: bytes) -> dict[str, str]:
    """corpCode.xml(zip) → {종목코드(6): 고유번호(8)}. 비상장(stock_code 공백)은 제외."""
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
        root = ET.fromstring(zf.read(name))
    out: dict[str, str] = {}
    for el in root.iter("list"):
        stock = (el.findtext("stock_code") or "").strip()
        corp = (el.findtext("corp_code") or "").strip()
        if len(stock) == 6 and corp:
            out.setdefault(stock, corp)
    return out


def load_dart_corp_map(key: str) -> dict[str, str]:
    """종목코드→고유번호 매핑. 신선한 캐시 → 다운로드 → (실패 시) 낡은 캐시 순."""
    cached = _read_json(config.DART_CORP_CACHE) or {}
    cmap = cached.get("map") or {}
    if cmap:
        try:
            age = (date.today() - date.fromisoformat(cached.get("fetched", ""))).days
        except ValueError:
            age = 10**6
        if age <= config.DART_CORP_CACHE_MAX_AGE_DAYS:
            return cmap
    try:
        payload = _download(config.DART_CORPCODE_URL.format(key=key), timeout=60)
        fresh = _parse_corpcode_zip(payload)  # 키 오류 시 zip이 아닌 XML 에러 응답 → BadZipFile
    except Exception as exc:
        if cmap:
            logger.warning("DART corpCode 재수집 실패 → 낡은 캐시 사용(%d종목): %s", len(cmap), exc)
            return cmap
        raise
    if fresh:
        _write_json(config.DART_CORP_CACHE, {"fetched": date.today().isoformat(), "map": fresh})
        return fresh
    return cmap


def _latest_nps_shares(items: list[dict]) -> int | None:
    """majorstock list에서 국민연금 보고 중 최신(접수일·접수번호 기준)의 보유주식등수."""
    best: tuple[tuple[str, str], int] | None = None
    for it in items or []:
        if config.DART_NPS_REPORTER_SUBSTR not in str(it.get("repror") or ""):
            continue
        qty = _pi(it.get("stkqy"))
        if not qty or qty <= 0:
            continue
        rcept_dt = re.sub(r"\D", "", str(it.get("rcept_dt") or ""))  # "2026-04-13"/"20260413" 모두 흡수
        sort_key = (rcept_dt, str(it.get("rcept_no") or ""))
        if best is None or sort_key > best[0]:
            best = (sort_key, qty)
    return best[1] if best else None


def fetch_dart_nps_shares(holdings: list[dict]) -> dict[str, int]:
    """국민연금 대량보유 공시의 최신 보유주식수 {종목코드: shares}. 실패·키 없음 시 빈 dict."""
    key = _dart_key()
    if not key:
        logger.info("DART_API_KEY 없음 → DART 공시 수량 생략")
        return {}
    cands = [h for h in holdings
             if (h.get("ownership_pct") or 0) >= config.DART_CANDIDATE_MIN_OWNERSHIP_PCT]
    if not cands:
        return {}
    try:
        corp_map = load_dart_corp_map(key)
    except Exception as exc:
        logger.warning("DART corpCode 매핑 실패(FnGuide/연말 수량 유지): %s", exc)
        return {}
    if not corp_map:
        logger.warning("DART corpCode 매핑이 비어 있음 → DART 생략")
        return {}
    out: dict[str, int] = {}
    unmapped = 0
    for h in cands:
        corp = corp_map.get(h["stock_code"])
        if not corp:
            unmapped += 1
            continue
        try:
            raw = _download(config.DART_MAJORSTOCK_URL.format(key=key, corp_code=corp),
                            timeout=20, retries=2)
            res = json.loads(raw.decode("utf-8"))
        except Exception:
            continue  # 개별 종목 실패는 건너뜀(해당 종목은 기존 수량 유지)
        status = str(res.get("status"))
        if status in _ABORT_STATUSES:
            logger.warning("DART status=%s(%s) → DART 수집 중단(이후 종목 생략)",
                           status, res.get("message"))
            break
        if status != "000":  # 013=조회 데이터 없음 등 → 해당 종목만 건너뜀
            continue
        qty = _latest_nps_shares(res.get("list") or [])
        if qty:
            out[h["stock_code"]] = qty
    logger.info("DART 대량보유: 후보 %d종목 중 %d종목 수량 확보(매핑 없음 %d)",
                len(cands), len(out), unmapped)
    return out
