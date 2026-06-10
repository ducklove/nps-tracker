"""종목코드 매핑 — corp_codes(DART 상장사 전체) + stock_meta + 별칭, 정확/정규화/prefix 매칭."""
from __future__ import annotations

import os
import re

from . import config
from .io_utils import _read_json


def _norm_name(s) -> str:
    return re.sub(r"[\s·._()/-]+", "", str(s or "").upper())


def load_resolver():
    """종목명 → 종목코드 리졸버. corp_codes(DART 상장사 전체) + stock_meta + aliases.

    반환: (정확명 맵, 정규화명 맵, (이름, 코드) 리스트[prefix 매칭용]).
    공개데이터 단축명과 DART 정식명 차이(예: 한국전력→한국전력공사)는 정규화·prefix로 흡수한다.
    """
    exact: dict[str, str] = {}
    normed: dict[str, str] = {}
    by_name: list[tuple[str, str]] = []
    corp = _read_json(os.path.join(config.DATA, "corp_codes.json"), {}) or {}  # {name: code}
    for name, code in corp.items():
        exact.setdefault(name, code)
        normed.setdefault(_norm_name(name), code)
        by_name.append((name, code))
    meta = _read_json(os.path.join(config.DATA, "stock_meta.json"), {}) or {}  # {code: name}
    for code, name in meta.items():
        if name and len(str(code)) == 6:
            exact.setdefault(str(name).strip(), str(code))
            normed.setdefault(_norm_name(name), str(code))
    for name, code in config._NPS_NAME_ALIASES.items():
        exact[name] = code  # 별칭이 우선(덮어쓰기)
    return exact, normed, by_name


def resolve_code(name: str, resolver) -> str:
    exact, normed, by_name = resolver
    n = str(name or "").strip()
    if n in exact:
        return exact[n]
    nn = _norm_name(n)
    if nn in normed:
        return normed[nn]
    cands = {code for nm, code in by_name if nm.startswith(n)}  # prefix가 유일할 때만
    if len(cands) == 1:
        return next(iter(cands))
    return ""
