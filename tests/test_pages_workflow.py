"""Pages 배포 계약(X0) — 아티팩트는 허용 목록(_site)만, 토큰·캐시는 절대 공개하지 않는다.

배경: `upload-pages-artifact path: .`가 .gitignore 대상인 data/kis_token.json(KIS 접근 토큰)과
data/price_cache.json(19.8 MB)·업종/DART 캐시·파이썬 소스까지 Pages로 공개했다(2026-09-30 확인).
"""
from __future__ import annotations

import os
import re

import pytest

yaml = pytest.importorskip("yaml")  # requirements-dev.txt

from scripts import stage_pages  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS = os.path.join(REPO, ".github", "workflows")
SECRETS = ("data/kis_token.json", "data/price_cache.json", "data/dart_corp_codes.json", "data/sector_cache.json")


def _load(name):
    with open(os.path.join(WORKFLOWS, name), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _steps(doc):
    return [s for job in doc["jobs"].values() for s in job.get("steps", [])]


@pytest.mark.parametrize("name", sorted(n for n in os.listdir(WORKFLOWS) if n.endswith((".yml", ".yaml"))))
def test_workflow_yaml_parses(name):
    doc = _load(name)
    assert isinstance(doc, dict) and doc.get("jobs"), name
    # PyYAML은 'on' 키를 True로 읽는다 — 트리거 블록이 있는지만 확인
    assert "on" in doc or True in doc, name


def test_pages_uploads_only_staged_site():
    steps = _steps(_load("pages.yml"))
    uploads = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-pages-artifact")]
    assert len(uploads) == 1
    path = str(uploads[0].get("with", {}).get("path", "")).strip()
    assert path not in ("", ".", "./"), "작업 트리 전체 업로드 금지"
    assert path == "_site"
    names = [s.get("name") for s in steps]
    stage_idx = next(i for i, s in enumerate(steps) if "stage_pages.py" in str(s.get("run", "")))
    assert stage_idx < steps.index(uploads[0]), "스테이징이 업로드보다 먼저여야 한다"
    stage_run = steps[stage_idx]["run"]
    assert "rm -f data/kis_token.json" in stage_run
    assert re.search(r"stage_pages\.py\s+_site\b", stage_run), names


def test_pages_commit_step_publishes_summary():
    steps = _steps(_load("pages.yml"))
    commit = next(s for s in steps if s.get("id") == "commit_data")
    assert "summary.json" in commit["run"] and "version.json" in commit["run"]
    for secret in SECRETS:
        assert secret not in commit["run"]


def test_allowlist_excludes_tokens_and_caches():
    listed = set(stage_pages.REQUIRED_FILES) | set(stage_pages.OPTIONAL_FILES)
    for secret in SECRETS:
        assert secret not in listed
        assert secret in stage_pages.FORBIDDEN
        assert not any(secret.startswith(d + "/") for d in stage_pages.DIRS)
    # 파이썬 소스·테스트·워크플로 디렉터리는 공개 대상이 아니다
    for d in stage_pages.DIRS:
        assert d.split("/")[0] not in ("nps_tracker", "tests", "scripts", ".github", "docs")


def test_stage_copies_site_and_skips_secrets(tmp_path):
    src = tmp_path / "repo"
    for rel in stage_pages.REQUIRED_FILES + ["summary.json", "assets/app.js", "data/archive/holdings_2024-12-31.json",
                                              *SECRETS, "nps_tracker/config.py", ".env"]:
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    dest = tmp_path / "_site"
    copied = set(stage_pages.stage(str(dest), root=str(src)))
    assert "index.html" in copied and "summary.json" in copied and "assets/app.js" in copied
    assert "data/archive/holdings_2024-12-31.json" in copied
    staged = {str(p.relative_to(dest)).replace(os.sep, "/") for p in dest.rglob("*") if p.is_file()}
    assert staged == copied
    for bad in (*SECRETS, "nps_tracker/config.py", ".env"):
        assert bad not in staged


def test_stage_fails_when_required_file_missing(tmp_path):
    (tmp_path / "index.html").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit):
        stage_pages.stage(str(tmp_path / "_site"), root=str(tmp_path))


def test_every_local_reference_in_index_is_staged():
    """index.html·app.js가 불러오는 로컬 파일은 모두 아티팩트에 있어야 한다(허용 목록 누락 = 배포 후 404)."""
    with open(os.path.join(REPO, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(REPO, "assets", "app.js"), encoding="utf-8") as f:
        app = f.read()
    refs = set(re.findall(r'(?:href|src)="(?:\./)?([^"#?:]+)(?:\?[^"]*)?"', html))
    refs |= set(re.findall(r"fetch\('([^'?]+)", app)) | set(re.findall(r"src='([^'?]+)", app))
    refs = {r for r in refs if r and not r.startswith(("http", "//"))}
    listed = set(stage_pages.REQUIRED_FILES) | set(stage_pages.OPTIONAL_FILES)
    missing = [r for r in sorted(refs) if r not in listed and not any(r.startswith(d + "/") for d in stage_pages.DIRS)]
    assert not missing, missing
    assert {"vc-shell.js", "vc-tokens.css", "data.json", "current.json", "version.json"} <= refs | listed
