"""_download — 재시도, 호스트 타임아웃 회로차단기. 전부 오프라인(urlopen monkeypatch)."""
from __future__ import annotations

import urllib.error

import pytest

from nps_tracker import http as nps_http


class FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._body


class ScriptedUrlopen:
    """호출 순서대로 예외 또는 본문을 돌려주는 urlopen 대역. 스크립트 소진 후엔 마지막 항목 반복."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def __call__(self, req, timeout=None):
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return FakeResp(item)


def _timeout_exc() -> Exception:
    return urllib.error.URLError(TimeoutError("timed out"))


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    monkeypatch.setattr(nps_http.time, "sleep", lambda s: None)


def test_success_returns_body(monkeypatch):
    fake = ScriptedUrlopen([b"payload"])
    monkeypatch.setattr(nps_http.urllib.request, "urlopen", fake)
    assert nps_http._download("https://ok.example/a") == b"payload"
    assert fake.calls == 1


def test_timeout_opens_breaker_and_skips_same_host(monkeypatch):
    fake = ScriptedUrlopen([_timeout_exc()])
    monkeypatch.setattr(nps_http.urllib.request, "urlopen", fake)
    # 첫 호출: 타임아웃 2회 누적 → 회로 열림 → 3번째 시도 없이 실패
    with pytest.raises(Exception, match="timed out"):
        nps_http._download("https://blocked.example/a", retries=3)
    assert fake.calls == 2
    # 같은 호스트의 후속 호출은 네트워크 시도 없이 즉시 실패
    with pytest.raises(nps_http.HostBlockedError):
        nps_http._download("https://blocked.example/b", retries=3)
    assert fake.calls == 2
    # 다른 호스트는 회로와 무관하게 정상 시도
    ok = ScriptedUrlopen([b"fine"])
    monkeypatch.setattr(nps_http.urllib.request, "urlopen", ok)
    assert nps_http._download("https://other.example/c") == b"fine"


def test_non_timeout_errors_do_not_open_breaker(monkeypatch):
    fake = ScriptedUrlopen([urllib.error.HTTPError("u", 404, "nf", None, None)])
    monkeypatch.setattr(nps_http.urllib.request, "urlopen", fake)
    with pytest.raises(urllib.error.HTTPError):
        nps_http._download("https://h404.example/a", retries=3)
    assert fake.calls == 3  # 재시도는 전부 수행(회로 미개방)
    with pytest.raises(urllib.error.HTTPError):
        nps_http._download("https://h404.example/b", retries=2)
    assert fake.calls == 5  # 후속 호출도 차단되지 않음


def test_success_resets_timeout_counter(monkeypatch):
    fake = ScriptedUrlopen([_timeout_exc(), b"ok", _timeout_exc(), _timeout_exc()])
    monkeypatch.setattr(nps_http.urllib.request, "urlopen", fake)
    # 타임아웃 1회 후 성공 → 카운터 리셋
    assert nps_http._download("https://flaky.example/a", retries=3) == b"ok"
    # 다시 타임아웃 2회가 쌓여야 회로가 열린다(리셋이 안 됐다면 1회 만에 열림)
    with pytest.raises(Exception, match="timed out"):
        nps_http._download("https://flaky.example/b", retries=3)
    assert fake.calls == 4
