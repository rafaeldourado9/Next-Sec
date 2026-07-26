# ─── Base com CUDA (GPU) ────────────────────────────────────────────────────
FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Dependências de sistema necessárias para OpenCV e libs nativas
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Garante pip e setuptools atualizados antes de instalar dependências
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Torch CPU em camada própria: wheel menor (~200 MB) do index oficial PyTorch,
# isolado do resto das deps para sobreviver a quedas de conexão (layer cache).
RUN pip install --no-cache-dir --retries 20 --timeout 600 \
    torch torchvision \
    --index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml .
RUN mkdir -p src && pip install --no-cache-dir --retries 20 --timeout 600 .

# ─── Produção GPU (CUDA) ───────────────────────────────────────────────────
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS gpu

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC

# Instalar Python 3.12 via deadsnakes PPA (Ubuntu 22.04 não tem 3.12 no apt padrão)
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    curl \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && ln -sf /usr/bin/python3.12 /usr/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3 \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Instalar PyTorch com suporte a CUDA
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir --retries 20 --timeout 600 \
    torch torchvision \
    --index-url https://download.pytorch.org/whl/cu124

COPY pyproject.toml .
RUN mkdir -p src && pip install --no-cache-dir --retries 20 --timeout 600 .

COPY src/ src/

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8001/health').raise_for_status()" || exit 1

CMD ["uvicorn", "analytics.main:app", "--host", "0.0.0.0", "--port", "8001"]

# ─── Produção CPU (fallback) ─────────────────────────────────────────────────
FROM base AS cpu

COPY src/ src/

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8001/health').raise_for_status()" || exit 1

CMD ["uvicorn", "analytics.main:app", "--host", "0.0.0.0", "--port", "8001"]

# ─── Target padrão: GPU ─────────────────────────────────────────────────────
FROM gpu AS production
