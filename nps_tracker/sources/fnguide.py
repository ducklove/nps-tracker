"""FnGuide 기관보유 수집 — 공시종목(지분율 5%↑ 대량보유)의 최신 분기 보유주식수."""
from __future__ import annotations

import logging

from .. import config
from ..http import _download
from ..resolver import resolve_code

logger = logging.getLogger("nps")


def fetch_fnguide_holdings() -> list[dict]:
    """FnGuide 기관보유 페이지에서 (종목명, 보유주식수)를 파싱. 지분율 5%↑ 대량보유 종목만 게재된다."""
    payload = _download(config.FNGUIDE_URL)
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(payload, "html.parser")
    out = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue
        t = [td.get_text(strip=True) for td in tds]
        try:
            int(t[0])  # rank 컬럼이 숫자인 행만
        except (ValueError, IndexError):
            continue
        s = t[2].replace(",", "")
        shares = int(s) if s.lstrip("-").isdigit() else 0
        if shares > 0:
            out.append({"name": t[1], "shares": shares})
    return out


def fetch_fnguide_shares(resolver) -> dict[str, int]:
    """공시종목(5%↑) 최신 분기 보유주식수 {종목코드: shares}. 실패 시 빈 dict(공공 수량 유지)."""
    try:
        rows = fetch_fnguide_holdings()
    except Exception as exc:
        logger.warning("FnGuide 수량 조회 실패(공공 연말 수량 유지): %s", exc)
        return {}
    out: dict[str, int] = {}
    for r in rows:
        code = resolve_code(r["name"], resolver)
        if code and len(code) == 6:
            out[code] = r["shares"]
    return out
