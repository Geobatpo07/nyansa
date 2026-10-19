# Build stage: the locked dependencies into a virtualenv, and the sources.
ARG PYTHON_IMAGE=python:3.14.7-slim-trixie

FROM ghcr.io/astral-sh/uv:0.12.3 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src /app/src
RUN python -m compileall -q /app/src

# Runtime stage: Python, the virtualenv and the sources (no uv), non-root.
# The bytecode is compiled at build time: the root filesystem is read-only.
FROM ${PYTHON_IMAGE}
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY --from=build /app /app
WORKDIR /app
USER 65532:65532
EXPOSE 8080
CMD ["python", "-m", "src.main"]
