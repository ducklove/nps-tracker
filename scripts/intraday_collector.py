#!/usr/bin/env python3
"""연기금 장중 매매동향 수집기 — pi-worker 상주 데몬(systemd: nps-intraday.service).

KIS 「시장별 투자자매매동향(시세성)」(FHPTJ04030000)을 장중 1분 간격으로 폴링해
연기금(fund_*) 잠정 누적치를 당일 시계열로 적립하고 OUT_DIR/intraday.json에 원자적으로
쓴다. Caddy가 https://cantabile.tplinkdns.com/nps/intraday.json 으로 서빙한다(CORS *).

- 데이터는 코스콤 장중 잠정 집계로, 장 마감 후 확정치와 다를 수 있다(프런트에 '잠정' 표기).
- '연기금'은 국민연금을 포함한 연기금 전체 카테고리다(단독 분리는 어떤 소스로도 불가).
- 휴장일·장외에는 전 필드가 0 → 포인트를 적립하지 않으므로 파일의 date가 직전 거래일에
  머무르고, 프런트는 date==오늘일 때만 섹션을 표시한다.
- KIS 자격증명: systemd EnvironmentFile(기존 kis_proxy/.env 재사용, KIS_APP_KEY/KIS_APP_SECRET).
  토큰은 KIS의 24시간 동일-토큰 반환 정책 덕에 다른 소비자(kis_proxy·Actions)와 공유 안전.
- 의존성 없음(표준 라이브러리만) — 파이 재설치·파이썬 업그레이드에도 견고.

사용: python3 intraday_collector.py [--out /srv/nps-intraday] [--once]
  --once: 1회 폴링 후 종료(플러밍 점검용). systemd에서는 무한 루프로 상주.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
BASE_URL = os.environ.get("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443").rstrip("/")
TR_ID = "FHPTJ04030000"
PBMN_TO_KRW = 1_000_000  # 응답 금액 단위: 백만원
MARKETS = ({"name": "kospi", "symbol": "0001", "market": "KSP"},
           {"name": "kosdaq", "symbol": "1001", "market": "KSQ"})
POLL_SEC = 60          # 장중 폴링 간격(잠정치 갱신 주기가 분 단위라 이보다 촘촘할 필요 없음)
IDLE_SEC = 300         # 장외 대기
OPEN_HHMM, CLOSE_HHMM = "0850", "1540"  # 폴링 창(동시호가 전 ~ 마감 확정 여유)
TOKEN_CACHE = os.path.expanduser("~/.cache/nps-intraday/kis_token.json")


def log(msg: str) -> None:
    print(f"[{datetime.now(KST):%F %T}] {msg}", flush=True)


def _request_json(method: str, url: str, headers: dict, body: dict | None = None,
                  query: dict | None = None, timeout: int = 15) -> dict:
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_token(app_key: str, app_secret: str) -> str:
    try:
        with open(TOKEN_CACHE, encoding="utf-8") as f:
            cached = json.load(f)
        if cached.get("access_token") and float(cached.get("expires_at", 0)) > time.time() + 300:
            return cached["access_token"]
    except (OSError, ValueError):
        pass
    payload = _request_json("POST", f"{BASE_URL}/oauth2/tokenP",
                            headers={"content-type": "application/json; charset=utf-8"},
                            body={"grant_type": "client_credentials",
                                  "appkey": app_key, "appsecret": app_secret})
    token = payload.get("access_token")
    if not token:
        raise RuntimeError(f"KIS token 발급 실패: {payload.get('msg1') or payload}")
    expires_in = int(payload.get("expires_in") or 23 * 3600)
    os.makedirs(os.path.dirname(TOKEN_CACHE), exist_ok=True)
    with open(TOKEN_CACHE, "w", encoding="utf-8") as f:
        json.dump({"access_token": token, "expires_at": time.time() + expires_in - 120}, f)
    return token


def fetch_market(token: str, app_key: str, app_secret: str, spec: dict) -> dict | None:
    """한 시장의 연기금 잠정 누적치. 실패 시 None(해당 사이클 생략)."""
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key, "appsecret": app_secret,
        "tr_id": TR_ID, "custtype": "P",
    }
    # FID_INPUT_ISCD=시장구분(KSP/KSQ), FID_INPUT_ISCD_2=업종코드(0001/1001) — 순서가 바뀌면
    # KIS가 오류 대신 rt_cd=0에 전 필드 0을 반환해 '휴장'으로 오판되므로 주의.
    payload = _request_json("GET", f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-investor-time-by-market",
                            headers=headers,
                            query={"FID_INPUT_ISCD": spec["market"], "FID_INPUT_ISCD_2": spec["symbol"]})
    if payload.get("rt_cd") not in (None, "0", 0):
        log(f"{spec['name']} 응답 오류: {payload.get('msg1')}")
        return None
    out = payload.get("output") or payload.get("output1") or {}
    row = out[0] if isinstance(out, list) and out else out
    if not isinstance(row, dict):
        return None

    def num(key):
        try:
            return int(str(row.get(key, "0")).replace(",", "") or 0)
        except ValueError:
            return 0

    return {
        "netValue": num("fund_ntby_tr_pbmn") * PBMN_TO_KRW,
        "netShares": num("fund_ntby_qty"),
        # 시장 전체 거래 유무 판단용(휴장/개장 전 스킵) — 개인 매도대금이 0이면 장이 안 선 것
        "_active": num("prsn_seln_tr_pbmn") > 0,
    }


def atomic_write(path: str, obj: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def in_window(now: datetime) -> bool:
    return now.weekday() < 5 and OPEN_HHMM <= now.strftime("%H%M") <= CLOSE_HHMM


def poll_once(out_dir: str, app_key: str, app_secret: str) -> str:
    """1회 수집. 반환: 상태 문자열(로그·검증용)."""
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    out_path = os.path.join(out_dir, "intraday.json")
    token = get_token(app_key, app_secret)
    markets = {}
    for spec in MARKETS:
        try:
            markets[spec["name"]] = fetch_market(token, app_key, app_secret, spec)
        except Exception as exc:
            log(f"{spec['name']} 조회 실패: {exc}")
            markets[spec["name"]] = None
    ok = {k: v for k, v in markets.items() if v}
    if not ok:
        return "양 시장 조회 실패"
    active = any(v["_active"] for v in ok.values())

    state = load_state(out_path)
    if state.get("date") != today:
        if state.get("date") and state.get("series"):  # 전 거래일 아카이브
            arch = os.path.join(out_dir, "archive")
            os.makedirs(arch, exist_ok=True)
            atomic_write(os.path.join(arch, f"{state['date']}.json"), state)
        state = {"date": today, "series": []}
    if not active and not state.get("series"):
        return "장 미개장(전 필드 0) — 적립 생략"

    point = {"time": now.strftime("%H:%M")}
    total = 0
    for name in ("kospi", "kosdaq"):
        v = markets.get(name)
        point[name] = v["netValue"] if v else None
        total += v["netValue"] if v else 0
    point["total"] = total
    series = state.get("series") or []
    if series and series[-1]["time"] == point["time"]:
        series[-1] = point  # 같은 분 재실행이면 교체
    else:
        series.append(point)
    state.update({
        "date": today,
        "updated": now.strftime("%Y-%m-%d %H:%M:%S"),
        "unit": "KRW",
        "source": "KIS Open API investor-time-by-market (장중 잠정 집계)",
        "note": "연기금 카테고리(국민연금 포함 합산) 당일 누적 순매수 — 확정치와 다를 수 있음",
        "series": series,
    })
    atomic_write(out_path, state)
    return f"적립 {point['time']} total={total/1e8:.0f}억 (points={len(series)})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/srv/nps-intraday")
    ap.add_argument("--once", action="store_true", help="1회 폴링 후 종료(플러밍 점검)")
    args = ap.parse_args()
    app_key = (os.environ.get("KIS_APP_KEY") or "").strip()
    app_secret = (os.environ.get("KIS_APP_SECRET") or "").strip()
    if not app_key or not app_secret:
        sys.exit("KIS_APP_KEY/KIS_APP_SECRET 환경변수가 없습니다(EnvironmentFile 확인).")
    os.makedirs(args.out, exist_ok=True)
    if args.once:
        log(poll_once(args.out, app_key, app_secret))
        return
    log(f"수집 시작 — 창 {OPEN_HHMM}~{CLOSE_HHMM} KST, {POLL_SEC}s 간격, out={args.out}")
    while True:
        now = datetime.now(KST)
        if in_window(now):
            try:
                log(poll_once(args.out, app_key, app_secret))
            except Exception as exc:  # 일시 오류는 다음 사이클에 재시도(systemd가 크래시도 복구)
                log(f"사이클 오류: {exc}")
            time.sleep(POLL_SEC)
        else:
            time.sleep(IDLE_SEC)


if __name__ == "__main__":
    main()
