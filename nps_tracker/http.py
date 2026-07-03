"""HTTP 다운로드 유틸 — 재시도 포함 다운로드, 호스트 회로차단기, 병렬 페이서, 한국어 CSV 디코딩."""
from __future__ import annotations

import threading
import time
import urllib.parse
import urllib.request

from . import config

# 같은 실행에서 호스트별 연속 타임아웃 횟수. 한도에 도달하면 그 호스트로의 요청을 즉시 실패시킨다.
# (data.go.kr·KOSIS는 클라우드/일부 로컬에서 상시 차단 — 매 호출 20~60초 타임아웃을 기다리는 낭비 제거.)
_HOST_TIMEOUT_LIMIT = 2
_host_timeouts: dict[str, int] = {}


class HostBlockedError(OSError):
    """연속 타임아웃이 누적된 호스트로의 요청을 이번 실행에서는 건너뛴다는 표시."""


def _reset_host_breaker() -> None:
    """회로차단기 상태 초기화(테스트용)."""
    _host_timeouts.clear()


def _is_timeout(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()


def _download(url: str, referer: str | None = None, timeout: int = 20, retries: int = 3) -> bytes:
    host = urllib.parse.urlsplit(url).hostname or ""
    headers = {"User-Agent": config._USER_AGENT}
    if referer:
        headers["Referer"] = referer
    last: Exception | None = None
    for attempt in range(retries):
        if _host_timeouts.get(host, 0) >= _HOST_TIMEOUT_LIMIT:
            if last:
                raise last
            raise HostBlockedError(f"{host} 연속 타임아웃 {_host_timeouts[host]}회 → 이번 실행에서는 건너뜀")
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = resp.read()
            _host_timeouts.pop(host, None)  # 성공 → 누적 타임아웃 리셋
            return payload
        except Exception as exc:  # data.go.kr은 간헐적으로 연결을 끊는다 → 재시도
            last = exc
            if _is_timeout(exc):
                _host_timeouts[host] = _host_timeouts.get(host, 0) + 1
            if attempt < retries - 1:
                time.sleep(2)
    raise last


class _Pacer:
    """스레드 간 최소 호출 간격을 강제한다(락을 잡은 채 대기 → 간격이 직렬화됨).

    외부 API 병렬 호출 시 초당 요청 수를 한도 아래로 유지하는 용도(KIS 20/s, DART 1000/min).
    """

    def __init__(self, interval_sec: float):
        self.interval = float(interval_sec)
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self._lock:
            delay = self._last + self.interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


def _decode_csv(payload: bytes) -> str:
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return payload.decode(enc)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", "replace")
