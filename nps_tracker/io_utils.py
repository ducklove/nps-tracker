"""입출력 유틸 — JSON 읽기/쓰기, 날짜·숫자 파싱."""
from __future__ import annotations

import json
import logging
import os

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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


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
