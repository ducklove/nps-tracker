"""GitHub Pages 아티팩트 스테이징 — 공개 사이트 파일만 허용 목록으로 _site/에 복사한다(X0).

배경: pages.yml이 `upload-pages-artifact path: .`로 작업 트리 전체를 올려, .gitignore 대상인
data/kis_token.json(KIS 접근 토큰)·data/price_cache.json(19.8 MB)·업종/DART 캐시와 파이썬 소스까지
공개 서빙됐다. 아티팩트는 이 스크립트가 만든 _site/만 올린다.

허용 목록은 index.html·assets/app.js가 실제로 불러오는 파일 + 외부 소비자 계약(docs/embed.md,
허브 생태계 계약의 summary.json/version.json)에서 도출한다. 새 공개 파일을 추가하면 여기에도 추가할 것
(tests/test_pages_workflow.py가 index.html 로컬 참조가 모두 포함되는지 검증한다).

    python3 scripts/stage_pages.py [_site]      # 표준 라이브러리만 사용(러너 기본 python3로 실행)
"""
from __future__ import annotations

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 반드시 있어야 하는 파일(없으면 스테이징 실패 → 배포 중단)
REQUIRED_FILES = [
    "index.html",
    "analytics.js",
    "manifest.webmanifest",
    "vc-shell.js",       # Value Compass 에코시스템 바(허브에서 벤더링)
    "vc-tokens.css",     # 공용 디자인 토큰(허브에서 벤더링)
    "data.json",
    "data.js",
    "current.json",
    "feed.xml",
    "data/holdings_latest.csv",
    "data/nav_history.json",
]
# 있으면 복사하는 파일(초기 발행 전 등 없을 수 있음)
OPTIONAL_FILES = [
    "summary.json",      # 허브용 요약(생태계 발행 데이터 계약 v1)
    "version.json",
    ".nojekyll",
]
# 통째로 복사하는 디렉터리(공개 정적 자산·불변 연말 아카이브)
DIRS = [
    "assets",
    "data/archive",
]

# 절대 공개하면 안 되는 경로(방어적 검사 — 허용 목록에 실수로 들어와도 실패시킨다)
FORBIDDEN = (
    "data/kis_token.json",
    "data/price_cache.json",
    "data/dart_corp_codes.json",
    "data/sector_cache.json",
    ".env",
)


def stage(dest: str, root: str = ROOT) -> list[str]:
    """허용 목록을 dest로 복사하고 복사된 상대 경로 목록을 반환한다. dest는 매번 새로 만든다."""
    dest = os.path.abspath(dest)
    if os.path.abspath(root) == dest:
        raise SystemExit("dest must differ from the repo root")
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    copied: list[str] = []

    def _copy(rel: str) -> None:
        if rel in FORBIDDEN or os.path.basename(rel).startswith(".env"):
            raise SystemExit(f"forbidden path in allowlist: {rel}")
        target = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(os.path.join(root, rel), target)
        copied.append(rel)

    missing = [rel for rel in REQUIRED_FILES if not os.path.isfile(os.path.join(root, rel))]
    if missing:
        raise SystemExit("missing required site files: " + ", ".join(missing))
    for rel in REQUIRED_FILES:
        _copy(rel)
    for rel in OPTIONAL_FILES:
        if os.path.isfile(os.path.join(root, rel)):
            _copy(rel)
    for d in DIRS:
        base = os.path.join(root, d)
        if not os.path.isdir(base):
            continue
        for cur, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(n for n in dirnames if not n.startswith((".", "__")))
            for name in sorted(filenames):
                if name.startswith("."):
                    continue
                _copy(os.path.relpath(os.path.join(cur, name), root).replace(os.sep, "/"))
    return copied


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    dest = args[0] if args else os.path.join(ROOT, "_site")
    copied = stage(dest)
    total = sum(os.path.getsize(os.path.join(dest, rel)) for rel in copied)
    print(f"staged {len(copied)} files ({total / 1e6:.2f} MB) into {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
