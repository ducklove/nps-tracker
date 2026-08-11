"""기금운용본부 월간 공시 수집 — 목록 파싱·xlsx 파싱·스킵/검증 규칙. 네트워크는 monkeypatch."""
from __future__ import annotations

import pytest

from nps_tracker.sources import npsfund
from tests.conftest import read_fixture

DETAIL_HTML = (
    '<div class="file"><a href="javascript:fncAtchFileDownload(\'FL26002797\', \'1\');">'
    "자산군별 포트폴리오 운용 현황 및 수익률 공시자료(2026. 5월).xlsx</a>"
    "<a href=\"javascript:fncAtchFileDownload('FL26002797', '2');\">운용 수익률 설명자료.pdf</a></div>"
)
FUND_KEYS = ("domestic_stock", "foreign_stock", "domestic_bond", "foreign_bond", "alternative", "short_term")


def _fake_download(calls: list[str], xlsx: bytes | None = None, detail: str = DETAIL_HTML):
    """목록 → 상세 → 첨부 3단계를 URL로 구분해 응답하는 가짜 다운로더."""
    def download(url, referer=None, **kw):
        calls.append(url)
        if "getOHEF0001M0" in url:
            return read_fixture("npsfund_list.html")
        if "getOHEF0006M0" in url:
            return detail.encode("utf-8")
        if "fileDown.do" in url:
            return b"%PDF-1.4 fake" if "atchFileSn=2" in url else (xlsx or read_fixture("npsfund.xlsx"))
        raise AssertionError(f"예상치 못한 URL: {url}")
    return download


# ---------- 목록 ----------
def test_parse_list_picks_asset_class_posts_only():
    """같은 월간 공시 목록의 「조성·지출·적립 현황」은 자산군 평가액이 아니므로 제외."""
    listed = npsfund._parse_list(read_fixture("npsfund_list.html").decode("utf-8"))

    assert listed == [("2026-05", "5925"), ("2026-04", "5915")]


# ---------- xlsx ----------
def test_parse_fund_xlsx_reads_month_end_amounts():
    as_of, values = npsfund._parse_fund_xlsx(read_fixture("npsfund.xlsx"))

    assert as_of == "2026-05"
    assert values["domestic_stock"] == 543_634_800_000_000  # 십억원 → 원
    assert values["short_term"] == 4_197_500_000_000
    assert set(values) == set(FUND_KEYS)


def test_parse_fund_xlsx_stops_before_yield_table():
    """아래 「자산군별 수익률」 표에도 같은 자산군명이 나온다 — 평가액 자리에 %가 들어오면 안 된다."""
    _, values = npsfund._parse_fund_xlsx(read_fixture("npsfund.xlsx"))

    assert values["domestic_stock"] > 100e12  # 수익률 106.76을 잘못 읽으면 106.76십억원이 된다
    assert values["foreign_stock"] == 650_679_400_000_000


# ---------- 수집 ----------
def test_fetch_returns_new_periods(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(npsfund, "_download", _fake_download(calls))

    rows = npsfund.fetch_nps_fund_monthly(known_periods={"2026-04"}, max_fetch=3)

    assert [r["period"] for r in rows] == ["2026-05"]
    assert rows[0]["source"] == "npsfund"
    assert all(k in rows[0] for k in FUND_KEYS)
    assert sum("getOHEF0006M0" in c for c in calls) == 1  # 이미 있는 월은 상세를 열지 않는다


def test_fetch_skips_when_all_known(monkeypatch):
    """정상 운영 시엔 새 공표월이 없다 — 목록 1회만 받고 다운로드는 하지 않는다."""
    calls: list[str] = []
    monkeypatch.setattr(npsfund, "_download", _fake_download(calls))

    assert npsfund.fetch_nps_fund_monthly({"2026-05", "2026-04"}) is None
    assert len(calls) == 1


def test_fetch_respects_max_fetch(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(npsfund, "_download", _fake_download(calls))

    rows = npsfund.fetch_nps_fund_monthly(known_periods=set(), max_fetch=1)

    assert len(rows) == 1
    assert sum("fileDown.do" in c for c in calls) == 1


def test_fetch_drops_month_when_file_period_mismatches(monkeypatch):
    """제목(2026.4월)과 파일 기준월(2026.5월)이 어긋나면 첨부 교체 사고 — 헛값 대신 생략."""
    calls: list[str] = []
    monkeypatch.setattr(npsfund, "_download", _fake_download(calls))

    rows = npsfund.fetch_nps_fund_monthly(known_periods={"2026-05"}, max_fetch=3)

    assert rows is None  # 픽스처 xlsx는 항상 2026-05 기준 → 2026-04 요청과 불일치


def test_fetch_ignores_pdf_attachment_order(monkeypatch):
    """첨부 순서가 PDF 먼저여도 xlsx를 찾아 쓴다(zip 시그니처로 판별)."""
    calls: list[str] = []
    flipped = DETAIL_HTML.replace("'1'", "'X'").replace("'2'", "'1'").replace("'X'", "'2'")
    monkeypatch.setattr(npsfund, "_download", _fake_download(calls, detail=flipped))

    rows = npsfund.fetch_nps_fund_monthly(known_periods={"2026-04"}, max_fetch=3)

    assert [r["period"] for r in rows] == ["2026-05"]


def test_fetch_returns_none_when_list_unavailable(monkeypatch):
    """목록 수집이 실패해도 예외를 밖으로 던지지 않는다(다른 소스로 폴백)."""
    def boom(url, referer=None, **kw):
        raise TimeoutError("timed out")

    monkeypatch.setattr(npsfund, "_download", boom)

    assert npsfund.fetch_nps_fund_monthly(set()) is None


def test_fetch_drops_month_with_missing_asset_class(monkeypatch):
    """자산군이 하나라도 빠지면 그 달은 통째로 생략한다(부분 레코드 금지)."""
    calls: list[str] = []
    monkeypatch.setattr(npsfund, "_download", _fake_download(calls))
    monkeypatch.setattr(npsfund, "_parse_fund_xlsx",
                        lambda payload: ("2026-05", {"domestic_stock": 1, "foreign_stock": 2}))

    assert npsfund.fetch_nps_fund_monthly({"2026-04"}, max_fetch=1) is None


# ---------- 시계열 합성 통합 ----------
def test_get_fund_portfolio_prefers_sheet_over_disclosure(monkeypatch, tmp_repo):
    """공시는 시트(사용자 SSOT)보다 아래, 나머지 소스보다 위 — 겹치는 월은 시트가 이긴다."""
    from nps_tracker import fund

    monkeypatch.setattr(fund, "fetch_kosis_fund_monthly", lambda: None)
    monkeypatch.setattr(fund, "fetch_fund_portfolio", lambda: None)
    monkeypatch.setattr(fund, "estimate_recent_months", lambda *a, **k: [])
    monkeypatch.setattr(fund, "fetch_nps_fund_monthly", lambda known=None: [
        {"period": "2026-04", "source": "npsfund", **{k: 10 for k in FUND_KEYS}},
        {"period": "2026-05", "source": "npsfund", **{k: 20 for k in FUND_KEYS}},
    ])
    monkeypatch.setattr(fund, "fetch_sheet_fund", lambda: [
        {"period": "2026-04", "source": "sheet", **{k: 99 for k in FUND_KEYS}},
    ])

    fp = fund.get_fund_portfolio()
    by_period = {s["period"]: s for s in fp["series"]}

    assert by_period["2026-04"]["source"] == "sheet"
    assert by_period["2026-05"]["source"] == "npsfund"
    assert fp["asOf"] == "2026-05"


def test_get_fund_portfolio_skips_periods_already_confirmed(monkeypatch, tmp_repo):
    """이미 확정값이 있는 월은 공시 수집에 known_periods로 넘겨 재다운로드를 막는다."""
    from nps_tracker import fund

    seen: dict[str, set] = {}

    def spy(known=None):
        seen["known"] = known
        return None

    monkeypatch.setattr(fund, "fetch_kosis_fund_monthly", lambda: [
        {"period": "2026-03", **{k: 5 for k in FUND_KEYS}},
    ])
    monkeypatch.setattr(fund, "fetch_fund_portfolio", lambda: None)
    monkeypatch.setattr(fund, "fetch_sheet_fund", lambda: None)
    monkeypatch.setattr(fund, "estimate_recent_months", lambda *a, **k: [])
    monkeypatch.setattr(fund, "fetch_nps_fund_monthly", spy)

    fund.get_fund_portfolio()

    assert "2026-03" in seen["known"]


@pytest.mark.parametrize("title,expected", [
    ("자산군별 포트폴리오 운용 현황 및 수익률(2026.5월)", ("2026", "5")),
    ("자산군별 포트폴리오 운용 현황 및 수익률(2025.12월)", ("2025", "12")),
    ("조성·지출·적립 현황(2026.5월)", None),
])
def test_title_regex(title, expected):
    from nps_tracker import config

    m = config._NPS_FUND_TITLE_RE.search(title)

    assert (m.groups() if m else None) == expected
