"""국민연금(NPS) 국내주식 포트폴리오 데이터 파이프라인 패키지.

fetch_data.py(단일 파일)를 수집(sources) · 계산(fund/nav) · 검증(validate) · 발행(publish)으로
분리한 것이다. 실행 진입점은 nps_tracker.cli.main() (저장소 루트의 fetch_data.py는 thin wrapper).
"""

__version__ = "2.0.0"
