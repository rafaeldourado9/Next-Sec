#!/bin/sh
# Roda cloudflared e captura a URL do tunnel quick automaticamente.
# Escreve a URL em /tunnel/url para a API consumir.

TUNNEL_FILE="/tunnel/url"
mkdir -p "$(dirname "$TUNNEL_FILE")"

cloudflared "$@" 2>&1 | while IFS= read -r line; do
    printf '%s\n' "$line"
    url=$(printf '%s' "$line" | grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' 2>/dev/null || true)
    if [ -n "$url" ]; then
        printf '%s' "$url" > "$TUNNEL_FILE"
    fi
done
