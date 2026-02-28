# syntax=docker/dockerfile:1.7
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REPO_ROOT=/app \
    HOST=0.0.0.0 \
    PORT=8000 \
    JOBCOACH_DB_PATH=/data/jobcoach.sqlite3 \
    MIGRATE_DB_PATH=/data/jobcoach.sqlite3 \
    JOBCOACH_AUTO_MIGRATE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash curl make ruby tini \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN useradd --create-home --shell /bin/bash --uid 10001 appuser \
    && mkdir -p /data /app/.tmp \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--", "bash", "/app/tools/scripts/docker-entrypoint.sh"]
CMD ["python3", "apps/api-gateway/serve.py"]
