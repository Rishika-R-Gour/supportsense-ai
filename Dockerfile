FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SUPPORTSENSE_ENV=production

WORKDIR /app

RUN groupadd --system supportsense \
    && useradd --system --gid supportsense --home-dir /app supportsense

COPY requirements-production.lock ./
RUN pip install --upgrade pip \
    && pip install --require-hashes -r requirements-production.lock

COPY app ./app
COPY supportsense ./supportsense
COPY migrations ./migrations
COPY alembic.ini ./

USER supportsense
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"

CMD ["uvicorn", "supportsense.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
