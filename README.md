# Quant Lab

토스증권 공식 Open API의 미국 주식 시세로 규칙 기반 전략을 실행하고, 실제 주문 없이 내부 모의 체결(DRY RUN)로 결과를 추적하는 개인용 퀀트 실험 도구입니다.

| 문서 | 내용 |
| --- | --- |
| [docs/project.md](docs/project.md) | 설계의 단일 출처: 범위, 원칙, 아키텍처, 기술 스택, 인프라, 작업 방식 |
| [docs/roadmap.md](docs/roadmap.md) | 단계별 계획과 현재 진행 상태 |
| [docs/tossApi.md](docs/tossApi.md) | 토스증권 Open API 조사·실측 결과 |

## 로컬 실행

필요한 도구: [uv](https://docs.astral.sh/uv/), Python 3.14, Node.js LTS, Docker Desktop.

```bash
cp .env.example .env                      # 필요하면 값 채우기
docker compose up -d --wait db            # PostgreSQL 17
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn quant_lab.api.main:app --reload   # http://localhost:8000/api/health
uv run python -m quant_lab.worker                # 다른 터미널
cd ../frontend
npm install
npm run dev                                       # http://localhost:5173
```

## 검사

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run python -m mypy
uv run pytest            # DB 테스트는 compose DB의 quant_lab_test를 사용, DB가 없으면 건너뜀
cd ../frontend
npm run lint && npm run build
```

Windows에서 `mypy.exe`가 애플리케이션 제어 정책으로 막히면 위처럼 `python -m mypy`로 실행합니다.

## CLI

```bash
cd backend
uv run python -m quant_lab.cli sync-bars QQQ VOO   # 토스 일봉을 DB에 동기화 (처음엔 전체, 이후 증분)
uv run python -m quant_lab.cli backtest QQQ --params fast=50,slow=200          # SMA 교차
uv run python -m quant_lab.cli backtest QQQ --strategy donchian --params entry=55,exit=20 --start 2010-01-04 --save
uv run python -m quant_lab.cli bot create qqq-sma QQQ --params fast=50,slow=200   # DRY RUN 봇 (STOPPED)
uv run python -m quant_lab.cli bot list
uv run python -m quant_lab.cli bot cmd <봇 ID> START                                # START·PAUSE·STOP·RUN_ONCE
uv run python -m quant_lab.cli replay QQQ --start 2024-01-02 --end 2026-09-30      # 정기 평가 재생 vs 백테스트
```

## 운영 배포

서울 리전 VM 1대에서 Docker Compose로 실행하고 화면은 Tailscale로만 엽니다. 절차는 [project.md 6절](docs/project.md).

```bash
cd infra/lightsail && terraform apply   # 서버 생성 (AWS 자격 증명 필요)
sudo bash deploy/bootstrap.sh   # 새 서버에서 한 번
bash deploy/deploy.sh           # 배포할 때마다 (main 기준)
```

## 토스 API 탐색

```bash
uv run scripts/toss_probe.py            # 읽기 전용 시세·종목·장 운영 API만 호출
```

실행할 때마다 토큰을 새로 발급하므로, 같은 client로 돌고 있는 서버 Worker의 토큰이 무효화됩니다.
