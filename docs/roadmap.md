# 로드맵

> 설계는 [project.md](project.md), 토스 API 사실은 [tossApi.md](tossApi.md). 단계가 끝나거나 순서가 바뀌면 이 문서를 갱신한다.
> 상태: `대기` · `진행` · `완료`. 최종 갱신: 2026-10-01.

## 현재 위치

**Phase 0 진행.** 탐색 스크립트(`scripts/toss_probe.py`) 준비 완료. 개발 PC 허용 IP 등록과 `.env` 작성 후 실제 호출 검증.

## 진행 순서

가장 불확실한 것(토스 API)을 먼저 확인하고, 서버 배포는 화면이 생기는 시점에 바로 해서 운영 검증 기간을 일찍 시작한다.

| Phase | 이름 | 상태 | 완료 기준 |
| --- | --- | --- | --- |
| 0 | 토스 API 검증 | 진행 | [tossApi.md](tossApi.md) 6절의 확인 항목 전부 기록, 첫 종목·봉 주기 결정 |
| 1 | 프로젝트 기반 | 대기 | 새 PC에서 README대로 설치·테스트 통과, CI 녹색 |
| 2 | 시세·전략·백테스트 (CLI) | 대기 | 같은 조건 재실행 결과 일치, 미래 데이터 참조 테스트 통과 |
| 3 | Worker DRY RUN (로컬) | 대기 | 중복 주문 0건, 장애 주입 시 신규 주문 차단, 재시작 후 `PAUSED` |
| 4 | 배포·운영 화면 | 대기 | Tailscale로 서버 대시보드 접속, 정기 DRY RUN이 서버에서 실행 |
| 5 | MWP 마무리·운영 검증 | 대기 | 2주 무개입 운영, 백테스트·설정 화면, 한계 문서화 |

## Phase 0 — 토스 API 검증

목표: 설계의 전제가 맞는지 코드를 쓰기 전에 확인한다.

- [x] 로컬 도구 설치: uv 0.12 (winget), Python 3.13.15 (`uv python install`)
- [ ] Docker Desktop (Phase 1 전까지)
- [x] 토스 WTS에서 Open API client 발급
- [ ] 허용 IP 개수 제한·client 다중 발급 가능 여부 확인 (WTS 화면)
- [ ] 개발 PC 공인 IP 등록 후 탐색 스크립트(`scripts/toss_probe.py`, 키는 환경변수)로 호출
  - [ ] 토큰 발급, `expires_in` 확인
  - [ ] 관심 목록 후보의 `/stocks` 응답 (지원 여부, `leverageFactor`)
  - [ ] `VOO`·`QQQ` 일봉 전체 페이지네이션 (첫 봉 날짜, 개수)
  - [ ] 1분봉 보존 기간
  - [ ] 미국 장 마감 후 일봉 확정 시점 (마감 직후부터 반복 조회)
  - [ ] rate limit 헤더 실제 값
- [ ] 결과를 `tossApi.md`에 반영하고 첫 종목·봉 주기를 `project.md` 9절에서 확정

산출물: 문서 갱신 PR 1개, 탐색 스크립트(실제 응답 데이터는 커밋하지 않음).

## Phase 1 — 프로젝트 기반

- [ ] `backend/` uv 프로젝트, `quant_lab` 패키지 골격 (project.md 4절 구조)
- [ ] ruff, mypy, pytest 설정. `domain`의 외부 의존 금지 테스트
- [ ] `compose.yaml` 로컬 PostgreSQL 17, Alembic 초기 마이그레이션
- [ ] pydantic-settings 설정, `.env.example` (변수 이름만)
- [ ] `frontend/` Vite + React + TS 골격
- [ ] GitHub Actions CI: backend(ruff·mypy·pytest + PostgreSQL 서비스), frontend(tsc·build)
- [ ] README에 설치·실행 방법

## Phase 2 — 시세·전략·백테스트 (CLI)

- [ ] 토스 어댑터: 토큰 관리자(단일 발급·만료 전 갱신·`token-revoked` 감지), 캔들·종목·캘린더 클라이언트, 429·오류 처리
- [ ] 봉 저장·검증: 누락·중복·이상치 검사, `Decimal` 변환, UTC 저장
- [ ] 장 운영 판정: `exchange_calendars` + 토스 캘린더 비교
- [ ] 전략 인터페이스와 첫 전략, 위험 규칙
- [ ] 모의 브로커: T+1 시가 체결, 수수료·슬리피지, 현금 원장, 포지션
- [ ] 백테스트 엔진과 CLI (`uv run python -m quant_lab.cli backtest ...`), 결과 DB 저장
- [ ] 테스트: 합성 데이터 기반 전략·체결·미래 데이터 차단, respx 기반 어댑터 테스트

## Phase 3 — Worker DRY RUN (로컬)

- [ ] Worker 루프: 명령 처리, `next_evaluation_at`, heartbeat
- [ ] 평가 1회 유스케이스 (project.md 4절 흐름), 판단 유일 키
- [ ] 봇 상태 전이와 재시작 복구 (`PAUSED`)
- [ ] 장애 주입 테스트: API 오류·데이터 지연·DB 끊김·Worker 2개 동시 실행
- [ ] 로컬에서는 저장된 봉으로 시간을 돌려 며칠치를 재생하는 모드

## Phase 4 — 배포·운영 화면

- [ ] FastAPI: 상태·포지션·실행 기록·이벤트 조회, 명령 기록 API
- [ ] 화면: 대시보드, 로그, 종목 차트 (project.md 8절)
- [ ] `deploy/compose.prod.yaml` (migrate → api·worker), 정적 파일 포함 이미지
- [ ] Lightsail 서울 2GB 생성, Static IP, 방화벽 차단, Tailscale, `tailscale serve`
- [ ] 서버 IP를 토스 허용 목록에 등록, Worker 시작
- [ ] `deploy/README.md` 서버 준비·배포·백업·복원 절차
- [ ] 매일 `pg_dump` 백업과 Lightsail 자동 스냅샷

## Phase 5 — MWP 마무리·운영 검증

- [ ] 백테스트 화면, 전략·설정 화면 (버전 관리)
- [ ] 2주 운영 기록: 실행 누락, 오류, 중복 여부를 확인하고 문제는 이슈로 남김
- [ ] 백업에서 실제로 복원해 보기
- [ ] 알려진 한계 문서화 → MWP 완료

## MWP 이후 (순서 미정)

| 항목 | 메모 |
| --- | --- |
| 알림 | 텔레그램 봇. 오류·주문·heartbeat 끊김 |
| 다종목 자동 실행 | 2–3종목. 포트폴리오 단위 위험 한도 |
| 장기 백테스트 데이터 | 2021-11 이전 데이터를 위한 별도 소스 검토 (데이터 이용 약관 확인) |
| 레버리지 ETF | 별도 위험 한도 검증 후 |
| 실시간 시세 | WebSocket 담당자 1개, 재연결·재구독 (tossApi.md 5절) |
| 전략 편집기 | 제한된 노드(시세·지표·조건·위험·주문·알림)부터 |
| 배포 자동화 | GitHub Actions + Tailscale SSH |
| **실거래** | 별도 게이트: 주문 어댑터, `clientOrderId` 멱등성, 계좌·주문 상태 대조, 비상 중지, 소액 한도. DRY RUN 결과와 비교 운영 후 결정 |
| 서버 이전 | OCI 또는 홈서버. 홈서버는 고정 IP 송신 경로 필요 (project.md 6절) |
