"""종목명 → 종목코드 리졸버 — 정확명/정규화/prefix 유일 매칭/별칭 우선순위."""
from __future__ import annotations

import json

import pytest

from nps_tracker.resolver import _norm_name, load_resolver, resolve_code


def test_norm_name_strips_spaces_and_specials():
    assert _norm_name("신세계 I&C") == "신세계I&C"
    assert _norm_name("ls electric") == "LSELECTRIC"
    assert _norm_name("미래에셋증권2우B") == "미래에셋증권2우B"
    assert _norm_name("CJ제일제당 우") == "CJ제일제당우"
    assert _norm_name("에이치·디(주)") == "에이치디주"  # ·, (, ), - 제거
    assert _norm_name(None) == ""


@pytest.fixture
def resolver(tmp_repo):
    data = tmp_repo / "data"
    # corp_codes: {정식명: 코드}
    (data / "corp_codes.json").write_text(json.dumps({
        "한국전력공사": "015760",
        "유일프리픽스산업": "111111",
        "중복프리픽스A": "222222",
        "중복프리픽스B": "333333",
        "삼성전자": "999999",  # 별칭(005930)이 이겨야 함
    }, ensure_ascii=False), encoding="utf-8")
    # stock_meta: {코드: 종목명}
    (data / "stock_meta.json").write_text(json.dumps({
        "035420": "NAVER",
        "1234567": "일곱자리코드",  # 6자리 아님 → 무시
    }, ensure_ascii=False), encoding="utf-8")
    return load_resolver()


def test_exact_match(resolver):
    assert resolve_code("한국전력공사", resolver) == "015760"


def test_normalized_match(resolver):
    # 공백·구분문자(·._()/-)는 정규화로 흡수된다. 단 괄호 "기호"만 제거되므로
    # "(주)" 같은 법인 접미의 글자는 남아 매칭되지 않는다(현행 의도된 동작).
    assert resolve_code("한국 전력 공사", resolver) == "015760"
    assert resolve_code("한국·전력공사", resolver) == "015760"
    assert resolve_code("한국전력공사(주)", resolver) == ""


def test_prefix_match_unique_only(resolver):
    assert resolve_code("유일프리픽스", resolver) == "111111"  # prefix 후보 1개 → 매칭
    assert resolve_code("중복프리픽스", resolver) == ""  # 후보 2개 → 실패(안전)
    assert resolve_code("없는종목", resolver) == ""


def test_alias_overrides_corp_codes(resolver):
    # corp_codes가 잘못된 코드를 갖고 있어도 내장 별칭이 우선
    assert resolve_code("삼성전자", resolver) == "005930"


def test_stock_meta_used(resolver):
    assert resolve_code("NAVER", resolver) == "035420"
    assert resolve_code("일곱자리코드", resolver) == ""  # 코드 6자리 아님 → 등재 안 됨


def test_empty_input(resolver):
    assert resolve_code("", resolver) == ""
    assert resolve_code(None, resolver) == ""
