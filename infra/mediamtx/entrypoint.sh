#!/bin/sh
# Renderiza /mediamtx.yml a partir do template (/mediamtx.yml.template),
# substituindo o placeholder __VMS_HOOKS_BASE_URL__ pelo valor real de
# VMS_HOOKS_BASE_URL. Ver comentário em mediamtx.yml (authHTTPAddress) —
# MediaMTX não aplica seu mecanismo nativo de override via env var (MTX_*)
# aos campos runOnReady/runOnNotReady/runOnRecordSegmentComplete
# (confirmado empiricamente: MTX_RUNONREADY é ignorado), então a base URL
# dos hooks/auth precisa ser resolvida aqui, antes do mediamtx subir.
set -eu

: "${VMS_HOOKS_BASE_URL:?defina VMS_HOOKS_BASE_URL (endereço alcançável da VMS API — http://api:8000 no compose central, ou o endereço da VPS central via túnel WireGuard no compose de edge — ver docs/DEPLOY_EDGE.md)}"

sed "s#__VMS_HOOKS_BASE_URL__#${VMS_HOOKS_BASE_URL}#g" /mediamtx.yml.template > /mediamtx.yml

exec /mediamtx /mediamtx.yml
