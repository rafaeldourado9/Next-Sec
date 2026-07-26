FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    # WeasyPrint dependencies (Sprint 10)
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# ─── Dependências Python ──────────────────────────────────────────────────────
FROM base AS deps

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# ─── Desenvolvimento ──────────────────────────────────────────────────────────
FROM deps AS development

RUN pip install --no-cache-dir -e ".[dev]"
COPY . .

CMD ["uvicorn", "vms.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ─── Produção ─────────────────────────────────────────────────────────────────
FROM deps AS production

COPY . .

# Rodar migrations e depois iniciar
CMD ["sh", "-c", "alembic upgrade head && uvicorn vms.main:app --host 0.0.0.0 --port 8000 --workers 4"]
