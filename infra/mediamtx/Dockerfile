FROM bluenviron/mediamtx:latest-ffmpeg

# curl é necessário para os hooks runOnReady / runOnNotReady / runOnRecordSegmentComplete
RUN apk add --no-cache curl

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
