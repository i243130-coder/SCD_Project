# syntax=docker/dockerfile:1
# Build context = repo root:  docker build -f services/agentops/Dockerfile -t $REGISTRY/agentops:$(git rev-parse --short HEAD) .
FROM python:3.12.7-slim-bookworm AS build
WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1

COPY libs/common /libs/common
COPY services/agentops/requirements.txt .
RUN pip install --prefix=/install -r requirements.txt /libs/common

FROM python:3.12.7-slim-bookworm
RUN useradd -m -u 10001 app
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=build /install /usr/local
COPY services/agentops/src/ ./src/
COPY registry.lock /app/registry.lock
ENV REGISTRY_LOCK=/app/registry.lock

USER 10001
EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
