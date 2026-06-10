"""발행 전 검증 게이트 — write_outputs 직전에 실행. (errors, warnings)를 반환한다.

errors  → 발행 중단(cli가 exit code 2, 기존 산출물 보존).
warnings → 발행물의 "warnings" 필드에 포함 + 로그.

일간 NAV 변동 검사는 **이전 발행 nav_history에 없던 새 날짜에만** 적용한다 — 기존 이력에
이미 ±8% 일간 변동이 있어(2026-06-08/09) 전체 이력을 검사하면 배치가 즉시 깨지기 때문.
ffill이 무제한이라(발행 NAV 보존을 위한 의도적 결정) 스테일 종목은 경고로만 보고한다.
임계값은 전부 config 상수.
"""
from __future__ import annotations

from datetime import date

from . import config


def run_validation(*, holdings: list[dict], evaluated: list[dict], prices: dict[str, list[dict]],
                   nav_hist: list[dict], prev_dates: set[str], total_value,
                   snap_date: str, src_date: str | None,
                   limit_used: bool = False) -> tuple[list[str], list[str]]:
    """발행 직전 데이터 정합성 검사.

    holdings  = 가격을 요청한 보유구성(--limit 적용 후), evaluated = snap_date 평가 결과,
    prev_dates = 이전 발행 nav_history의 날짜 집합(덮어쓰기 전에 읽은 것).
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not nav_hist:
        errors.append("NAV 시계열이 비어 있음 — 가격을 받지 못했을 수 있습니다")
        return errors, warnings

    # ① 가격 수신 종목 비율 (--limit는 부분 실행이라 비율 검사가 무의미 → 생략)
    if not limit_used and holdings:
        covered = sum(1 for h in holdings if prices.get(h["stock_code"]))
        ratio = covered / len(holdings)
        if ratio < config.MIN_PRICE_COVERAGE:
            errors.append(
                f"가격 수신 종목 비율 {ratio:.1%} < {config.MIN_PRICE_COVERAGE:.0%}"
                f" ({covered}/{len(holdings)}종목)"
            )

    # ② 평가총액
    if not total_value or total_value <= 0:
        errors.append(f"total_value={total_value} (양수가 아님)")

    # ③ '새 날짜'의 일간 NAV 변동 — 기존 발행 이력의 날짜는 검사하지 않음
    prev_dates = prev_dates or set()
    for prev, cur in zip(nav_hist, nav_hist[1:]):
        if cur["date"] in prev_dates or not prev.get("nav") or not cur.get("nav"):
            continue
        pct = (cur["nav"] / prev["nav"] - 1) * 100
        if abs(pct) > config.NAV_DAILY_ERROR_PCT:
            errors.append(f"{cur['date']} 일간 NAV {pct:+.1f}% — 한도 ±{config.NAV_DAILY_ERROR_PCT:.0f}% 초과")
        elif abs(pct) > config.NAV_DAILY_WARN_PCT:
            warnings.append(f"{cur['date']} 일간 NAV {pct:+.1f}% — 이상치/기업행위 확인 필요")

    # ④ 개별 종목 일간 등락 — 한국 시장 가격제한폭(±30%) 초과는 데이터 이상/기업행위 신호
    movers = [h for h in evaluated or []
              if h.get("change_pct") is not None and abs(h["change_pct"]) > config.STOCK_DAILY_LIMIT_PCT]
    if movers:
        movers.sort(key=lambda h: abs(h["change_pct"]), reverse=True)
        names = ", ".join(
            f"{h['stock_name']} {h['change_pct']:+.1f}%" for h in movers[:config.STOCK_LIMIT_WARN_MAX]
        )
        warnings.append(
            f"일간 등락 ±{config.STOCK_DAILY_LIMIT_PCT:.0f}%(가격제한폭) 초과 {len(movers)}종목: {names}"
        )

    # ⑤ 스테일 가격 — 마지막 실제 가격이 snap_date보다 N거래일 이상 과거(ffill로 옛 가격 평가 중)
    trading_days = [s["date"] for s in nav_hist]
    total_mv = sum(h.get("market_value") or 0 for h in evaluated or [])
    stale: list[tuple[float, str, str]] = []
    for h in evaluated or []:
        rows = [r for r in prices.get(h["stock_code"], []) if r.get("date") and r["date"] <= snap_date]
        if not rows:
            continue
        last_px = max(r["date"] for r in rows)
        behind = sum(1 for d in trading_days if last_px < d <= snap_date)
        weight = (h.get("market_value") or 0) / total_mv * 100 if total_mv else 0.0
        if behind >= config.STALE_PRICE_TRADING_DAYS and weight >= config.STALE_WEIGHT_MIN_PCT:
            stale.append((weight, h["stock_name"], last_px))
    if stale:
        stale.sort(reverse=True)
        names = ", ".join(f"{nm}(마지막 {d})" for _, nm, d in stale[:config.STALE_WARN_NAMES_MAX])
        warnings.append(
            f"가격 스테일 {len(stale)}종목(비중 ≥{config.STALE_WEIGHT_MIN_PCT}%): {names}"
            " — 거래정지/상폐 의심, 옛 가격으로 평가 중"
        )

    # ⑥ 보유 구성 기준일(src_date) 경과 — 연말 공시가 오래되면 구성 자체가 낡았음을 표시
    if src_date:
        age = (date.fromisoformat(snap_date) - date.fromisoformat(src_date)).days
        if age > config.COMPOSITION_MAX_AGE_DAYS:
            warnings.append(f"보유 구성이 {src_date} 연말 공시 기준 ({age}일 경과)")

    return errors, warnings
