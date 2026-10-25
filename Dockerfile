# Multi-stage build: dependencies are built in one stage and copied into a
# small final image, which then runs as a non-root user.

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN pip wheel --wheel-dir /wheels .

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --create-home --uid 10001 app
COPY --from=builder /wheels /wheels
RUN pip install /wheels/* && rm -rf /wheels
COPY alembic.ini ./
COPY migrations ./migrations
RUN mkdir -p /home/app/.cache && chown -R app:app /home/app/.cache
USER app
# fastembed stores downloaded models here (a volume in docker-compose, so it downloads once).
ENV EMBEDDING_CACHE_DIR=/home/app/.cache/fastembed
EXPOSE 8000
# The platform restarts the container if this fails repeatedly.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"
CMD ["uvicorn", "gst_copilot.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
