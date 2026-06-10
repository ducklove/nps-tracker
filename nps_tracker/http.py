"""HTTP 다운로드 유틸 — 재시도 포함 다운로드와 한국어 CSV 디코딩."""
from __future__ import annotations

import time
import urllib.request

from . import config


def _download(url: str, referer: str | None = None, timeout: int = 20, retries: int = 3) -> bytes:
    headers = {"User-Agent": config._USER_AGENT}
    if referer:
        headers["Referer"] = referer
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # data.go.kr은 간헐적으로 연결을 끊는다 → 재시도
            last = exc
            if attempt < retries - 1:
                time.sleep(2)
    raise last


def _decode_csv(payload: bytes) -> str:
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return payload.decode(enc)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", "replace")
