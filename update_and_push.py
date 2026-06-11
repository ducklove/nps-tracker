"""로컬 원클릭 갱신·발행 — pull → fetch_data.py → 데이터 산출물만 커밋 → push.

사용법:
    python update_and_push.py                  # 기본 실행
    python update_and_push.py --refresh-prices # 추가 인자는 fetch_data.py로 그대로 전달

동작 규칙:
- main 브랜치에서만 동작한다(다른 브랜치면 중단 — 데이터 커밋은 main으로만).
- 시작 시 `git pull --rebase --autostash`로 원격 최신을 받는다(코드 수정 중이어도 안전).
- fetch_data.py가 실패하면(검증 게이트 exit 2 포함) 아무것도 커밋하지 않는다.
- 커밋 대상은 데이터 산출물 경로만(워크플로우와 동일 목록) — 코드 수정은 스테이징하지 않는다.
- push가 거부되면(그 사이 Actions 봇이 커밋) rebase 후 재시도한다(최대 3회).
- push되면 GitHub Actions가 push 이벤트로 사이트를 자동 재배포한다.

DART_API_KEY / KOSIS_API_KEY 환경변수가 설정돼 있으면 해당 소스도 수집한다(없으면 생략).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))

# 워크플로우 'Commit refreshed data'와 동일한 커밋 대상(코드 파일은 절대 포함하지 않는다)
DATA_PATHS = [
    "data.js", "data.json", "current.json",
    "data/nav_history.json", "data/seed_fund_portfolio.json",
    "data/seed_holdings_latest.json", "data/archive",
]
OPTIONAL_PATHS = ["data/seed_foreign_holdings.json", "assets/og-image.png"]  # 없을 수 있음

PUSH_RETRIES = 3


def run(*cmd: str, check: bool = True) -> int:
    print("$", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=ROOT)
    if check and rc != 0:
        sys.exit(f"중단: `{' '.join(cmd)}` 실패(exit {rc})")
    return rc


def out(*cmd: str) -> str:
    return subprocess.check_output(cmd, cwd=ROOT, text=True, encoding="utf-8").strip()


def main() -> None:
    try:  # Windows 콘솔 한글 출력 보호(cli.py와 동일)
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    branch = out("git", "rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        sys.exit(f"중단: 현재 브랜치가 '{branch}'입니다. 데이터 발행은 main에서만 — `git checkout main` 후 재실행하세요.")

    # 1) 원격 최신 동기화(로컬 수정은 autostash로 보존)
    run("git", "pull", "--rebase", "--autostash", "origin", "main")

    # 2) 데이터 수집·발행(검증 게이트 실패 시 여기서 종료 → 커밋 없음)
    rc = subprocess.call([sys.executable, "fetch_data.py", *sys.argv[1:]], cwd=ROOT)
    if rc != 0:
        sys.exit(f"중단: fetch_data.py 실패(exit {rc}) — 산출물을 커밋하지 않습니다. 로그의 '검증 실패'를 확인하세요.")

    # 3) 데이터 경로만 스테이징
    run("git", "add", "--", *DATA_PATHS)
    for p in OPTIONAL_PATHS:
        if os.path.exists(os.path.join(ROOT, p)):
            run("git", "add", "--", p)

    if subprocess.call(["git", "diff", "--cached", "--quiet"], cwd=ROOT) == 0:
        print("변경된 데이터가 없습니다 — 커밋/푸시 생략.")
        return

    # 4) 커밋(봇 커밋과 구분되게 'local' 표기)
    run("git", "commit", "-m", f"Update NPS data ({date.today():%Y-%m-%d}, local)")

    # 5) push — 그 사이 Actions 봇이 커밋했으면 rebase 후 재시도
    for attempt in range(1, PUSH_RETRIES + 1):
        if subprocess.call(["git", "push", "origin", "main"], cwd=ROOT) == 0:
            break
        if attempt == PUSH_RETRIES:
            sys.exit("중단: push 실패가 반복됩니다. 네트워크/권한을 확인하고 수동으로 `git push origin main` 하세요.")
        print(f"push 거부됨(원격에 새 커밋 추정) — rebase 후 재시도 {attempt}/{PUSH_RETRIES - 1}")
        run("git", "pull", "--rebase", "--autostash", "origin", "main")
        time.sleep(2 * attempt)

    head = out("git", "log", "-1", "--format=%h %s")
    print(f"\n완료: {head}")
    print("GitHub Actions가 push를 감지해 사이트를 자동 재배포합니다(1~2분):")
    print("  https://ducklove.github.io/nps-tracker/")


if __name__ == "__main__":
    main()
