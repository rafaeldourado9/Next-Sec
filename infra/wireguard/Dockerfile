FROM python:3.12-slim

# NOTA (Next Sec): Debian slim + apt (não Alpine/apk) — o apk add já falhou
# neste ambiente por erro de certificado TLS contra dl-cdn.alpinelinux.org
# (ver infra/nginx/Dockerfile e infra/mediamtx/Dockerfile). apt-get contra os
# mirrors padrão do Debian já funciona em todo o resto do projeto (api/,
# analytics/, edge_agent/ usam a mesma base).
RUN apt-get update && apt-get install -y --no-install-recommends \
    wireguard-tools \
    socat \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY control_api.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Portas:
# 51820/udp  WireGuard
# 8080/tcp   API de controle interna (nunca publicada no host)
EXPOSE 51820/udp 8080

ENTRYPOINT ["./entrypoint.sh"]
