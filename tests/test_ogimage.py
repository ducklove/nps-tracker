"""OG 공유 카드(F-13) — PNG 생성·경로·헤더 검증. Pillow 없는 환경에서는 자동 스킵."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PIL")

from nps_tracker import config  # noqa: E402
from nps_tracker.ogimage import write_og_image  # noqa: E402


def _hist(n=30):
    return [{"date": f"2026-01-{i+1:02d}", "nav": 1000 + i * 3} for i in range(n)]


def test_write_og_image_creates_png(tmp_repo):
    out = write_og_image(_hist(), 3413.22, -4.49, "2026-06-10")
    assert out == os.path.join(config.ROOT, "assets", "og-image.png")
    with open(out, "rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"
    assert os.path.getsize(out) > 5_000


def test_write_og_image_sparse_history_ok(tmp_repo):
    """포인트가 1개뿐이거나 등락이 None이어도 그려진다(스파크라인만 생략)."""
    out = write_og_image(_hist(1), 1000.0, None, "2026-01-01")
    assert os.path.getsize(out) > 1_000
