"""공용 테스트 설정 — 저장소 루트를 sys.path에 추가, 경로 패치 픽스처.

모든 테스트는 오프라인이다(네트워크 호출 0). 외부 I/O는 전부 monkeypatch.
"""
from __future__ import annotations

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def read_fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """config의 모든 경로 상수를 tmp_path 밑으로 재지정한 격리 작업 디렉터리."""
    from nps_tracker import config

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "ROOT", str(tmp_path))
    monkeypatch.setattr(config, "DATA", str(data))
    monkeypatch.setattr(config, "SEED_HOLDINGS", str(data / "seed_holdings_latest.json"))
    monkeypatch.setattr(config, "SEED_FUND_PORTFOLIO", str(data / "seed_fund_portfolio.json"))
    monkeypatch.setattr(config, "NAV_HISTORY", str(data / "nav_history.json"))
    monkeypatch.setattr(config, "PRICE_CACHE", str(data / "price_cache.json"))
    monkeypatch.setattr(config, "DART_CORP_CACHE", str(data / "dart_corp_codes.json"))
    monkeypatch.setattr(config, "ARCHIVE_DIR", str(data / "archive"))
    monkeypatch.setattr(config, "SECTOR_CACHE", str(data / "sector_cache.json"))
    return tmp_path
