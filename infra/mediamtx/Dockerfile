FROM bluenviron/mediamtx:latest-ffmpeg

# NOTA (Next Sec): hooks (runOnReady/runOnNotReady) usam wget, não curl —
# wget já vem na imagem base (Alpine/BusyBox), evita depender do apk add
# (achado durante teste local: dl-cdn.alpinelinux.org falhava por erro de
# certificado TLS neste ambiente). Ver .genesis/architecture/reuse-plan.md.

# Configuração é um TEMPLATE (placeholder __VMS_HOOKS_BASE_URL__) — o
# entrypoint renderiza pra /mediamtx.yml de verdade no start do container,
# usando VMS_HOOKS_BASE_URL (ver entrypoint.sh e comentário em mediamtx.yml).
# Achado real durante S6-06/continuação: MediaMTX não aplica seu override
# nativo via env var (MTX_*) aos campos runOnReady/runOnNotReady/
# runOnRecordSegmentComplete — só um template resolvido no start funciona
# igual pros dois compose (central: api:8000: edge: túnel WireGuard).
COPY mediamtx.yml /mediamtx.yml.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

# Portas expostas:
# 8554  RTSP
# 1935  RTMP
# 8888  HLS
# 8889  WebRTC (HTTP + WHEP)
# 8189  WebRTC UDP (ICE)
# 9997  API de controle
# 9998  Métricas Prometheus
EXPOSE 8554 1935 8888 8889 8189/udp 9997 9998
