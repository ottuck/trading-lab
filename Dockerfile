# 운영 이미지 하나로 api·worker·migrate를 모두 실행한다 (시작 명령만 다름).
# 서버에서 직접 빌드하므로 x86(Lightsail)·ARM(OCI) 모두 그대로 쓴다.

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

ENV PATH=/app/.venv/bin:$PATH \
    FRONTEND_DIST=/app/frontend
RUN useradd --system --uid 10001 app
USER app
EXPOSE 8000
CMD ["uvicorn", "quant_lab.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
