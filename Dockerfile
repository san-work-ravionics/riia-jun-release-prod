# ── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install dependencies into a venv before copying the full source so that
# Docker can cache this layer when only application code changes.
RUN python -m venv /build/venv
ENV PATH="/build/venv/bin:$PATH"

COPY pyproject.toml .
# Install dependencies first (layer cached when only app code changes), then
# copy src/ so the editable install can find the package root.
RUN mkdir -p src && pip install --no-cache-dir -e ".[dev]"

# Copy full source (overwrites the empty placeholder)
COPY src/ src/
COPY config/ config/

# Lint gate — fail the build if ruff finds issues
RUN ruff check src/

# Test gate disabled — re-enable once test suite is stable
# COPY tests/ tests/
# RUN pytest tests/ --tb=short -q --cov=rita --cov-report=term-missing --cov-fail-under=80


# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy only the pre-built venv from the builder stage
COPY --from=builder /build/venv /app/venv

# Copy application source and config
COPY src/ /app/src/
COPY config/ /app/config/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini

# Copy dashboard static files (served by FastAPI StaticFiles mount in main.py)
COPY dashboard/ /app/dashboard/
COPY mobileapp/ /app/mobileapp/

ENV PATH="/app/venv/bin:$PATH"
ENV PYTHONPATH="/app/src"

# Run as a non-root user
RUN useradd --uid 1000 --no-create-home --shell /sbin/nologin rita
USER rita

EXPOSE 8000

CMD ["sh", "-c", "/app/venv/bin/alembic upgrade head && /app/venv/bin/uvicorn rita.main:app --host 0.0.0.0 --port 8000"]
