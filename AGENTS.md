# 에이전트 작업 원칙

이 저장소에서 일하는 AI 에이전트(Claude Code, Codex 등)가 늘 지킬 것. 설계와 결정의 원본은 `docs/project.md`이고, 여기에는 일하는 방식만 적는다. 개인 사이드 프로젝트라 **최근 결정이 앞선다**: 예전 규칙과 새 요청이 겹치면 새 요청을 따르고 낡은 규칙을 고친다 (project.md 10절).

## 말

- **사용자에게 하는 말은 모두 한국어로 쓴다.** 답변, 질문, 진행 상황, 작업을 마칠 때의 보고와 요약(앱의 다음 단계 상자 포함)까지 모두. 코드·명령·파일 이름·식별자는 그대로 둔다.
- 커밋 메시지와 PR 본문도 한국어로, 저장소의 기존 형식(`feat:`·`fix:`·`docs:`·`chore:`·`refactor:`·`infra:` + 한 줄 요약)을 따른다.
- 화면·알림 문구는 주식을 모르는 사람도 알아듣게 쉬운 말로 쓴다 (project.md 8절).

## 브랜치와 작업 공간

- 같은 체크아웃에서 여러 세션이 일하므로 **작업은 별도 worktree에서** 한다. 브랜치는 `origin/dev`에서 딴다 (`feat/…`, `fix/…`, `docs/…`, `chore/…`).
- 흐름: 작업 브랜치 → `dev` PR (squash 병합) → 배포할 때 `dev` → `main` (빨리 감기 push, project.md 10절). `main`에 push되면 CI 없이 바로 운영에 배포된다.
- 로컬 Docker 컨테이너는 일부러 꺼 둔다. DB가 꼭 필요할 때(백엔드 테스트, 데모 확인)만 켜고, 끝나면 끈다.
- 설정·비밀값은 저장소 안 `.secrets/`(git 제외)에 둔다. 저장소 밖 경로를 새로 만들지 않는다.

## CI

- CI(`.github/workflows/ci.yml`)는 **`dev`로 가는 PR에서 한 번만** 돈다 (Actions 분 절약). `dev` push·`dev → main` PR·`main` push에서는 돌지 않고, 문서·인프라만 바뀐 PR(`docs/**`, `**/*.md`, `infra/**`, `LICENSE`, `.claude/**`)은 건너뛴다.
- `verify` 잡 하나가 백엔드와 프런트를 함께 본다. PR을 올리기 전에 로컬에서 같은 것을 돌린다:
  - `backend`: `uv run ruff check .`, `uv run ruff format --check .`, `uv run python -m mypy`, `uv run alembic upgrade head && uv run alembic check`(모델과 마이그레이션 일치), `REQUIRE_DB=1 uv run pytest`
  - `frontend`: `npm ci`, `npm run lint`(oxlint), `npm run build`(tsc + vite)
- `dev`에는 필수 검사가 걸려 있지 않아 GitHub 자동 병합은 CI를 기다리지 않는다. CI 결과를 확인한 뒤 직접 병합한다.

## 테스트

- **꼭 필요한 테스트만 쓴다** (개인 프로젝트라 테스트 수와 CI 시간을 늘리지 않는다). 핵심 불변식(미래 데이터 안 보기, 다음 날 시가 체결, 중복 주문 방지, 재시작 시 멈춤, 토큰·403 처리, 백테스트와 재생의 일치, 계층 규칙)을 지키는 테스트가 우선이다.
- 기능 하나에 테스트는 1~3개까지. 경우마다 새 테스트를 만들지 말고 기존 테스트에 확인을 더하는 쪽을 먼저 고른다.

## 코드 경계

- 계층: `domain`(순수) ← `persistence`·`adapters` ← `application` ← `api`·`worker`. 쿼리는 `persistence`에서만 만든다 (`tests/test_architecture.py`가 지킨다).
- 엔진은 증권사를 모른다: 엔진은 `domain/broker.py` 규약만 알고, 토스 이름·개념·규칙은 `adapters/`와 조립 지점(`worker/__main__.py`, `cli.py`, `config.py`)에만 둔다.
- 비교하는 봇·평행세계는 비교하는 한 가지만 다르게 둔다. 그래프를 다양하게 보이려고 성격을 바꾸지 않는다.
- 문서는 `docs/project.md`(설계의 원본), `docs/roadmap.md`(진행), `docs/tossApi.md`(토스 API 조사)만 쓴다. 다른 문서 파일을 만들지 않고, 문서는 작업과 같은 PR에서 고친다.

## PR

- **라벨을 단다.** 종류 하나: `enhancement`(feat), `bug`(fix), `documentation`(문서만 또는 문서 비중이 큰 PR). 영역은 해당하면 더한다: `ui`(화면), `ops`(배포·서버·운영). `refactor`·`chore`는 영역 라벨만 단다.
- 본문은 무엇을, 확인한 것, 확인하지 못한 것(예: 실제 API를 부르지 않음, 서버에서 돌려 보지 않음)을 나눠 쓴다.
- **Codex 리뷰를 확인한다.** PR을 올리면 몇 분 안에 `chatgpt-codex-connector` 봇이 요약과 줄 단위 지적(P1·P2)을 단다. 병합 전에 읽고, 맞는 지적은 같은 PR에 커밋으로 고친다. 맞지 않는 지적은 고치지 않고 이유를 한 줄로 남긴다. CI가 끝날 때까지 리뷰가 오지 않으면 기다리지 않는다. 이미 병합한 PR에 나중에 온 지적도 다음 PR에서 고친다.

## 병합 권한

- **작업 PR(→ `dev`)은 CI가 통과하고 Codex 지적을 정리했으면 묻지 않고 squash 병합한다.** 병합 뒤 worktree와 로컬 브랜치를 정리한다.
- **다음은 "큰일"이라 멈추고 묻는다:** CI 실패를 고치지 못함, project.md 3절의 설계 원칙을 바꾸거나 어김, 실제 주문 경로 추가, 비밀값·토스 시세가 밖으로 나갈 위험, 돈이 드는 자원 만들기, 되돌리기 어려운 DB 변경.
- `dev` → `main` 배포는 project.md 10절의 절차를 따른다 (`git merge-base --is-ancestor origin/main origin/dev`를 확인한 뒤 빨리 감기 push, 강제 push 금지).
