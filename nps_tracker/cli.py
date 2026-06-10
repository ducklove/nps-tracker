"""실행 오케스트레이션(CLI) — 기존 fetch_data.py의 main()을 분해한 것.

흐름: 보유구성 확보(공공데이터→seed) → 가격 조회(증분 캐시) → FnGuide 수량 갱신 →
NAV 시계열 재계산 → KOSPI → 기금 포트폴리오 → 검증 게이트 → 발행.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from . import config
from .fund import get_fund_portfolio, load_baseline, save_baseline
from .io_utils import _read_json
from .nav import _evaluate_today, _mtd_pct, _today_change_pct, _ytd_pct, build_nav_history
from .publish import write_outputs
from .resolver import load_resolver
from .sources.dart import fetch_dart_nps_shares
from .sources.datago import get_public_holdings
from .sources.fnguide import fetch_fnguide_shares
from .sources.market import _close_on_before, get_kospi_cached, get_prices_cached
from .validate import run_validation

logger = logging.getLogger("nps")


def _setup_logging() -> None:
    try:  # Windows 콘솔에서도 한글 로그가 깨지지 않도록
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # 상폐 종목 폴백 노이즈 억제


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(description="국민연금 포트폴리오 대시보드 데이터 생성")
    ap.add_argument("--limit", type=int, default=0, help="테스트용 종목 수 제한")
    ap.add_argument("--until", default=None, help="기준일 상한 YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--no-public", action="store_true", help="공공데이터 생략(seed만 사용)")
    ap.add_argument("--refresh-prices", action="store_true",
                    help="가격 캐시 무시하고 전체 재조회(yfinance 데이터 재작성 대응)")
    return ap.parse_args(argv)


def _since_for(src_date: str) -> str:
    # 연말 기준일이 휴장일일 수 있어(예: 12-31), 직전 거래일 종가까지 포함하도록 앞당겨 조회
    return (date.fromisoformat(src_date) - timedelta(days=config.PRICE_SINCE_LOOKBACK_DAYS)).isoformat()


def _load_holdings(args, until: str):
    """보유구성 확보: 공공데이터(네트워크) 우선 → 실패 시 seed(정적 파일).

    반환: (holdings, src_date, source, prices).
    """
    pub = None if args.no_public else get_public_holdings()
    if pub:
        rows, src_date = pub
        codes = [r["stock_code"] for r in rows]
        since = _since_for(src_date)
        logger.info("공공데이터 %d종목, 종가 조회 %s ~ %s", len(codes), since, until)
        prices = get_prices_cached(codes, since, until, refresh=args.refresh_prices)
        # 공개 CSV는 주식수가 없으므로 연말 종가로 추정수량 환산
        holdings = []
        for r in rows:
            p0, _ = _close_on_before(prices.get(r["stock_code"], []), src_date)
            if p0 and r.get("source_market_value"):
                holdings.append({
                    "stock_code": r["stock_code"],
                    "stock_name": r["name"],
                    "shares": max(1, round(r["source_market_value"] / p0)),
                    "ownership_pct": r.get("ownership_pct", 0),
                })
        if len(holdings) >= config.MIN_RESOLVED_HOLDINGS:
            save_baseline(holdings, src_date)  # 정적 seed 갱신(클라우드 폴백용)
            return holdings, src_date, f"data.go.kr({src_date})", prices
        logger.warning("추정수량 환산 종목 부족(%d) → seed 폴백", len(holdings))

    # 클라우드(GitHub Actions)에서는 data.go.kr 접근이 막히므로 커밋된 정적 seed를 사용한다.
    holdings, src_date = load_baseline()
    if not holdings or not src_date:
        logger.error("seed 보유구성/기준일이 없습니다.")
        sys.exit(1)
    codes = [h["stock_code"] for h in holdings]
    since = _since_for(src_date)
    logger.info("seed %d종목, 종가 조회 %s ~ %s", len(codes), since, until)
    prices = get_prices_cached(codes, since, until, refresh=args.refresh_prices)
    return holdings, src_date, f"seed({src_date})", prices


def main(argv=None):
    _setup_logging()
    args = _parse_args(argv)

    until = args.until or date.today().isoformat()

    # 이전 발행 nav_history의 날짜 집합 — 재계산으로 덮어쓰기 전에 읽어 '새 날짜' 검증에 사용.
    prev_hist = _read_json(config.NAV_HISTORY, []) or []
    prev_dates = {s.get("date") for s in prev_hist if isinstance(s, dict) and s.get("date")}

    holdings, src_date, source, prices = _load_holdings(args, until)

    if args.limit:
        holdings = holdings[:args.limit]

    # 공시종목(5%↑ 대량보유) 수량을 최신 공시 값으로 갱신(공공 연말 추정수량 위에 덮음).
    # 우선순위: DART 대량보유 공시(공식 API, 공시 당일) > FnGuide(동일 공시의 집계 사이트) > 연말 추정.
    # 5% 미만 종목은 공시가 없어 연말 수량을 유지한다. 둘 다 실패하면 공공 수량 그대로.
    overrides = fetch_fnguide_shares(load_resolver())
    dart = fetch_dart_nps_shares(holdings)  # DART_API_KEY 없으면 빈 dict
    n_fg = len(overrides)
    overrides.update(dart)
    if overrides:
        applied = sum(1 for h in holdings
                      if h["stock_code"] in overrides and overrides[h["stock_code"]] != h["shares"])
        for h in holdings:
            if h["stock_code"] in overrides:
                h["shares"] = overrides[h["stock_code"]]
        logger.info("공시수량 갱신: FnGuide %d·DART %d종목 매칭, %d종목 변경", n_fg, len(dart), applied)

    nav_hist = build_nav_history(holdings, prices, src_date, until)
    if not nav_hist:
        logger.error("NAV 시계열 생성 실패 — 가격을 받지 못했을 수 있습니다.")
        sys.exit(2)
    snap_date = nav_hist[-1]["date"]
    valid = _evaluate_today(holdings, prices, snap_date)

    total_value = nav_hist[-1]["total_value"]
    nav = nav_hist[-1]["nav"]

    dates = [s["date"] for s in nav_hist]
    kospi = get_kospi_cached(min(dates), max(dates), refresh=args.refresh_prices)
    kospi = [k for k in kospi if k["date"] in set(dates)]

    today_pct = _today_change_pct(valid)
    mtd = _mtd_pct(nav_hist, snap_date)
    ytd = _ytd_pct(nav_hist, snap_date)

    # 기금 전체·부문별 평가액(시트 공표 + KOSIS + 추정). 추정월 국내주식엔 본 사이트 일별 평가액 사용.
    fund_portfolio = get_fund_portfolio(nav_hist)

    # 검증 게이트: 에러면 발행하지 않고 종료(기존 산출물 보존). 경고는 발행물에 포함.
    errors, warnings = run_validation(
        holdings=holdings, evaluated=valid, prices=prices, nav_hist=nav_hist,
        prev_dates=prev_dates, total_value=total_value, snap_date=snap_date,
        src_date=src_date, limit_used=bool(args.limit),
    )
    for w in warnings:
        logger.warning("검증 경고: %s", w)
    if errors:
        for e in errors:
            logger.error("검증 실패: %s", e)
        logger.error("발행 중단 — 기존 산출물을 보존합니다.")
        sys.exit(2)

    write_outputs(snap_date, source, valid, total_value, nav, today_pct, mtd, ytd,
                  nav_hist, kospi, fund_portfolio, warnings=warnings)
    fp_n = len(fund_portfolio["series"]) if fund_portfolio else 0
    logger.info("완료: %s | NAV %.2f | 국내주식 %.3f조 | %d종목 | %d일 | 기금부문 %d기간 | 출처 %s",
                snap_date, nav, total_value / 1e12, len(valid), len(nav_hist), fp_n, source)
