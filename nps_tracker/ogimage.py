"""OG 공유 카드 PNG 생성(F-13) — 일배치에서 NAV 요약 + 스파크라인을 1200×630으로 그린다.

폰트 의존을 없애기 위해 텍스트는 영문·숫자만 사용한다(DejaVu — GitHub 러너·대부분의
리눅스에 기본 탑재, 없으면 PIL 내장 폰트로 강등). Pillow가 없으면 호출부(cli)가 생략한다.
출력: assets/og-image.png (index.html og:image가 가리키는 경로, 워크플로우가 커밋).
"""
from __future__ import annotations

import os

from . import config

SIZE = (1200, 630)
BG = (15, 23, 42)        # slate-900 — 다크 테마 배경과 동일
FG = (226, 232, 240)     # slate-200
MUTED = (148, 163, 184)  # slate-400
UP = (252, 165, 165)     # 상승(한국 관례 적색 계열)
DOWN = (147, 197, 253)   # 하락(청색 계열)
ACCENT = (59, 130, 246)  # blue-500

_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
)


def _font(size: int, bold: bool = True):
    from PIL import ImageFont
    for p in _FONT_PATHS:
        if ("Bold" in p) != bold:
            continue
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    for p in _FONT_PATHS:  # bold/regular 구분 없이 재시도
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def write_og_image(nav_hist: list[dict], nav: float, today_pct: float | None,
                   snap_date: str, path: str | None = None) -> str:
    """공유 카드 PNG를 그려 저장하고 경로를 반환. Pillow 미설치 시 ImportError 전파(호출부 생략)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(img)
    w, h = SIZE
    pad = 70

    d.text((pad, 60), "NPS Korea Domestic Equity", font=_font(46), fill=FG)
    d.text((pad, 122), "National Pension Service portfolio tracker", font=_font(26, bold=False), fill=MUTED)

    d.text((pad, 210), f"NAV {nav:,.2f}", font=_font(88), fill=FG)
    if today_pct is not None:
        chg = f"{today_pct:+.2f}%"
        d.text((pad, 320), chg, font=_font(52), fill=(UP if today_pct > 0 else DOWN if today_pct < 0 else MUTED))
        d.text((pad + 60 + 30 * len(chg), 338), f"as of {snap_date}", font=_font(28, bold=False), fill=MUTED)
    else:
        d.text((pad, 330), f"as of {snap_date}", font=_font(28, bold=False), fill=MUTED)

    # 스파크라인: 최근 ~250포인트를 우측 절반 하단에. 데이터가 빈약하면 생략.
    series = [s["nav"] for s in (nav_hist or [])[-250:] if s.get("nav")]
    if len(series) >= 2:
        x0, y0, x1, y1 = pad, 440, w - pad, h - 70
        lo, hi = min(series), max(series)
        span = (hi - lo) or 1.0
        pts = [
            (x0 + (x1 - x0) * i / (len(series) - 1), y1 - (y1 - y0) * (v - lo) / span)
            for i, v in enumerate(series)
        ]
        d.line(pts, fill=ACCENT, width=4, joint="curve")
        d.line([(x0, y1 + 8), (x1, y1 + 8)], fill=(51, 65, 85), width=1)

    d.text((w - pad, h - 48), "ducklove.github.io/nps-tracker", font=_font(24, bold=False),
           fill=MUTED, anchor="ra")

    out = path or os.path.join(config.ROOT, "assets", "og-image.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out, "PNG")
    return out
