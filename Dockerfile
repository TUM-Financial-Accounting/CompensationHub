FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend .
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /srv
# Same layout as the repo: the backend resolves data/ and docs/ from the repo root.
COPY backend/pyproject.toml backend/uv.lock backend/
RUN cd backend && uv sync --frozen --no-dev
COPY backend/app backend/app
COPY data data
COPY docs docs
COPY --from=web /web/dist frontend/dist
ENV PATH="/srv/backend/.venv/bin:$PATH"
WORKDIR /srv/backend
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
