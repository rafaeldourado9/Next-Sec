FROM bluenviron/mediamtx:latest-ffmpeg

# NOTA (Next Sec): hooks (runOnReady/runOnNotReady) usam wget, não curl —
# wget já vem na imagem base (Alpine/BusyBox), evita depender do apk add
# (achado durante teste local: dl-cdn.alpinelinux.org falhava por erro de
# certificado TLS neste ambiente). Ver .genesis/architecture/reuse-plan.md.

# Copia configuração customizada
COPY mediamtx.yml /mediamtx.yml

# Portas expostas:
# 8554  RTSP
# 1935  RTMP
# 8888  HLS
# 8889  WebRTC (HTTP + WHEP)
# 8189  WebRTC UDP (ICE)
# 9997  API de controle
# 9998  Métricas Prometheus
EXPOSE 8554 1935 8888 8889 8189/udp 9997 9998
