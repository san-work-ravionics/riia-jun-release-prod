# ── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Build venv at /app/venv so shebang paths match the runtime container
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY pyproject.toml constraints-prod.txt ./
# Use extra-index-url (not index-url) so PyPI remains available for all other packages.
# This ensures pip finds the CPU-only torch wheel and won't pull in the 7 GB NVIDIA CUDA stack.
# constraints-prod.txt pins the ML stack to the model-training versions so
# image builds are reproducible — see the header of that file.
ARG PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -c constraints-prod.txt torch --extra-index-url https://download.pytorch.org/whl/cpu
# Install project deps; pip sees torch already satisfied so does not re-resolve to CUDA.
RUN mkdir -p src && pip install --no-cache-dir -c constraints-prod.txt -e ".[dev,interfaces]"

# Pre-download sentence-transformer model so the runtime image has no HuggingFace dependency.
# Placed after pip install but before COPY src/ so this layer is cached unless dependencies change.
RUN mkdir -p /app/models && \
    /app/venv/bin/python -c "\
from sentence_transformers import SentenceTransformer; \
m = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); \
m.save('/app/models/embed_model')" \
    || (pip show torch && python -c "import torch; print(torch.__version__)" && exit 1)
# Ensure model files are world-readable: newer huggingface_hub/safetensors writes
# model.safetensors as 0600, but the runtime container runs as non-root user `rita`
# (uid 1000) and cannot read it → classifier load fails with a misleading
# "No such file or directory". chmod -R a+rX makes every future image readable
# regardless of the saver's umask. See DEPLOYMENT_KNOWLEDGE PATTERN-016.
RUN chmod -R a+rX /app/models

# Copy full source (overwrites the empty placeholder)
COPY src/ src/
COPY config/ config/

# Lint gate — fail the build if ruff finds issues
RUN ruff check src/


# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy only the pre-built venv from the builder stage
COPY --from=builder /app/venv /app/venv

# Copy application source, config, and pre-built embed model
COPY src/ /app/src/
COPY config/ /app/config/
COPY --from=builder /app/models /app/models
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini

# Copy dashboard static files (served by FastAPI StaticFiles mount in main.py)
COPY dashboard/ /app/dashboard/
COPY mobileapp/ /app/mobileapp/
COPY ops/ /app/ops/
COPY test-results/ /app/test-results/

ENV PATH="/app/venv/bin:$PATH"
ENV PYTHONPATH="/app/src"

# Run as a non-root user
RUN useradd --uid 1000 --no-create-home --shell /sbin/nologin rita && \
    mkdir -p /app/logs && chown rita:rita /app/logs
USER rita

EXPOSE 8000

CMD ["sh", "-c", "/app/venv/bin/alembic upgrade head && /app/venv/bin/uvicorn rita.main:app --host 0.0.0.0 --port 8000"]
