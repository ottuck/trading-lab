# 운영 이미지 하나로 api·worker·migrate를 모두 실행한다 (시작 명령만 다름).
# CI(.github/workflows/deploy.yml)가 빌드해 GHCR에 올린다. 지금은 linux/amd64(Lightsail)만 만든다.
# ARM 서버(OCI·맥)로 옮기면 워크플로의 platforms에 linux/arm64를 추가한다.

FROM node:24-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --locked --no-dev
COPY --from=web /web/dist /app/frontend
# 이미지를 내려받는 사람에게도 라이선스(AGPL-3.0) 원문이 함께 가야 한다
COPY LICENSE /app/LICENSE

# 캔들분석 AI 봇의 차트 그림(matplotlib): 홈 폴더 없는 app 사용자라 설정·글꼴 캐시는 /tmp에 둔다
ENV PATH=/app/.venv/bin:$PATH \
    FRONTEND_DIST=/app/frontend \
    MPLCONFIGDIR=/tmp/matplotlib
# 이 이미지를 만든 커밋. 오류 보고(Sentry)가 어느 배포에서 난 오류인지 알려 준다.
ARG GIT_SHA=unknown
ENV SENTRY_RELEASE=$GIT_SHA
RUN useradd --system --uid 10001 app
USER app
EXPOSE 8000
CMD ["uvicorn", "trading_lab.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
