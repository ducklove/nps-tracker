"""입출력 유틸 — JSON 읽기/쓰기, 날짜·숫자 파싱."""
from __future__ import annotations

import json
import logging

from fin_commons.jsonio import atomic_write_text

logger = logging.getLogger("nps")


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as exc:
        logger.warning("read %s 실패: %s", path, exc)
        return default


def _write_json(path, obj):
    # 직렬화 형식은 기존 그대로(json.dump 기본 구분자), 쓰기만 원자적으로 (fin-commons)
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False))


def _yyyymmdd(iso: str) -> str:
    return iso.replace("-", "")


def _pf(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _pi(v):
    f = _pf(v)
    return int(f) if f is not None else None
