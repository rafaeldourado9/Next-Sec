<p align="center">
  <img src="logo.svg" width="180" alt="Arcanum API">
</p>

<h1 align="center">Arcanum API</h1>

<p align="center">
  <strong>Gateway WhatsApp open-source com anti-ban nativo, multi-instancia e suporte completo a midia.</strong>
</p>

<p align="center">
  <a href="#instalacao">Instalacao</a> •
  <a href="#inicio-rapido">Inicio Rapido</a> •
  <a href="#endpoints">Endpoints</a> •
  <a href="#anti-ban">Anti-Ban</a> •
  <a href="#configuracao">Configuracao</a> •
  <a href="#docker">Docker</a> •
  <a href="CONTRIBUTING.md">Contribuir</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Go-1.25-00ADD8?logo=go&logoColor=white" alt="Go 1.25">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT License">
  <img src="https://img.shields.io/badge/WhatsApp-Gateway-25D366?logo=whatsapp&logoColor=white" alt="WhatsApp">
  <img src="https://img.shields.io/badge/Status-Production_Ready-brightgreen" alt="Status">
  <img src="https://img.shields.io/badge/Anti--Ban-Built--in-purple" alt="Anti-Ban">
</p>

---

## O que e o Arcanum?

Arcanum API e um gateway WhatsApp standalone que conecta ao WhatsApp via protocolo web (whatsmeow) e expoe uma API REST completa. Pensado para ser o sucessor moderno do Evolution API.

### Diferenciais

- **Anti-ban nativo** — delay aleatorio, "digitando...", read receipts, rate limiting em todo envio
- **Multi-instancia** — gerencie multiplos numeros WhatsApp na mesma API
- **Midia completa** — imagem, audio, video, documento, localizacao, contato, enquete, reacao
- **Webhook configuravel** — URL, eventos e toggle por instancia via API
- **Provider-agnostico** — interface abstrata, pode trocar o engine sem mudar a API
- **Docker-first** — single binary, Alpine, pronto para producao
- **Swagger UI** — documentacao interativa em `/docs`

---

## Instalacao

### Docker (recomendado)

```bash
docker run -d \
  --name arcanum \
  -p 3100:3100 \
  -v arcanum_data:/data \
  ghcr.io/rafaeldourado9/arcanum:latest
```

### Docker Compose

```yaml
services:
  arcanum:
    image: ghcr.io/rafaeldourado9/arcanum:latest
    ports:
      - "3100:3100"
    environment:
      GATEWAY_PORT: "3100"
      GATEWAY_WEBHOOK_FORWARD_URL: "http://seu-backend:8000/webhook"
      GATEWAY_META_APP_SECRET: "seu-secret-para-hmac"
    volumes:
      - arcanum_data:/data

volumes:
  arcanum_data:
```

### Build manual

```bash
git clone https://github.com/rafaeldourado9/arcanum.git
cd arcanum
go build -o arcanum ./cmd/gateway
./arcanum
```

> Requer Go 1.25+ e CGO habilitado (para SQLite).

---

## Inicio Rapido

### 1. Inicie o Arcanum

```bash
docker compose up -d
```

### 2. Crie uma instancia

```bash
curl -X POST http://localhost:3100/api/instance/create \
  -H "Content-Type: application/json" \
  -d '{"instanceName": "meu-bot", "webhook": "http://meu-backend/webhook"}'
```

### 3. Conecte via QR Code

```bash
# Conectar (gera o QR)
curl http://localhost:3100/api/instance/connect/meu-bot

# Abra no browser para escanear
open http://localhost:3100/api/instance/qr/meu-bot?format=png
```

Escaneie o QR com o WhatsApp: **Configuracoes > Dispositivos conectados > Conectar dispositivo**

### 4. Envie uma mensagem

```bash
curl -X POST http://localhost:3100/api/message/sendText/meu-bot \
  -H "Content-Type: application/json" \
  -d '{"number": "5511999999999", "text": "Ola! Mensagem enviada pelo Arcanum."}'
```

### 5. Receba mensagens

Quando alguem enviar uma mensagem para o numero conectado, o Arcanum encaminha automaticamente para o webhook configurado com assinatura HMAC-SHA256.

---

## Endpoints

### Instancia

| Metodo | Endpoint | Descricao |
|--------|----------|-----------|
| `POST` | `/api/instance/create` | Criar instancia |
| `GET` | `/api/instance/connect/{nome}` | Conectar (gera QR) |
| `GET` | `/api/instance/connectionState/{nome}` | Status da conexao |
| `GET` | `/api/instance/qr/{nome}` | QR code (JSON ou `?format=png`) |
| `POST` | `/api/instance/pair/{nome}` | Pairing por telefone |
| `DELETE` | `/api/instance/logout/{nome}` | Desconectar |
| `DELETE` | `/api/instance/delete/{nome}` | Remover instancia |
| `POST` | `/api/instance/restart/{nome}` | Reconectar |
| `POST` | `/api/instance/setPresence/{nome}` | Definir presenca |
| `GET` | `/api/instance/fetchInstances` | Listar todas |

### Mensagens

| Metodo | Endpoint | Descricao |
|--------|----------|-----------|
| `POST` | `/api/message/sendText/{nome}` | Enviar texto (com anti-ban) |
| `POST` | `/api/message/sendMedia/{nome}` | Enviar imagem/audio/doc/video |
| `POST` | `/api/message/sendLocation/{nome}` | Enviar localizacao |
| `POST` | `/api/message/sendContact/{nome}` | Enviar contato (vCard) |
| `POST` | `/api/message/sendReaction/{nome}` | Enviar reacao (emoji) |
| `POST` | `/api/message/sendPoll/{nome}` | Enviar enquete |

### Chat

| Metodo | Endpoint | Descricao |
|--------|----------|-----------|
| `POST` | `/api/chat/markMessageAsRead/{nome}` | Marcar como lido |
| `POST` | `/api/chat/checkWhatsAppNumbers/{nome}` | Verificar numeros |
| `POST` | `/api/chat/updateProfileName/{nome}` | Atualizar nome |
| `POST` | `/api/chat/updateProfileStatus/{nome}` | Atualizar status |
| `POST` | `/api/chat/updateProfilePicture/{nome}` | Atualizar foto |
| `POST` | `/api/chat/archiveChat/{nome}` | Arquivar conversa |
| `POST` | `/api/chat/findChats/{nome}` | Listar conversas |
| `POST` | `/api/chat/findContacts/{nome}` | Listar contatos |
| `POST` | `/api/chat/findMessages/{nome}` | Buscar mensagens |

### Eventos

| Metodo | Endpoint | Descricao |
|--------|----------|-----------|
| `GET` | `/api/events/webhook/{nome}` | Ver config do webhook |
| `POST` | `/api/events/webhook/{nome}` | Configurar webhook |

### Configuracoes

| Metodo | Endpoint | Descricao |
|--------|----------|-----------|
| `GET` | `/api/settings/{nome}` | Ver configuracoes |
| `POST` | `/api/settings/{nome}` | Atualizar configuracoes |

### Sistema

| Metodo | Endpoint | Descricao |
|--------|----------|-----------|
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/docs/openapi.json` | OpenAPI spec |

---

## Anti-Ban

O Arcanum implementa medidas anti-ban em **todo envio de mensagem**, sem excecao:

```
1. Delay aleatorio (1.5 - 4 segundos)
2. Mark as Read (simula leitura)
3. Presence "digitando..." (composing)
4. Espera proporcional ao texto (50ms por caractere, 2-8s)
5. Presence "paused"
6. Pausa natural (200-600ms)
7. Envia a mensagem
```

Para audios, o passo 3 usa `"gravando..."` em vez de `"digitando..."`.

### Rate Limiting

- **15 mensagens por minuto** por instancia (configuravel)
- Sliding window de 60 segundos
- Responde HTTP 429 quando excedido

### Configuracao anti-ban

| Variavel | Padrao | Descricao |
|----------|--------|-----------|
| `GATEWAY_MIN_DELAY_MS` | 1500 | Delay minimo antes de responder |
| `GATEWAY_MAX_DELAY_MS` | 4000 | Delay maximo antes de responder |
| `GATEWAY_TYPING_DURATION_MS` | 2000 | Duracao minima do "digitando" |
| `GATEWAY_MS_PER_CHAR` | 50 | Milissegundos por caractere |
| `GATEWAY_MAX_TYPING_MS` | 8000 | Duracao maxima do "digitando" |
| `GATEWAY_RATE_LIMIT_PER_MIN` | 15 | Mensagens por minuto por instancia |

---

## Midia

### Enviar imagem

```bash
curl -X POST http://localhost:3100/api/message/sendMedia/meu-bot \
  -H "Content-Type: application/json" \
  -d '{
    "number": "5511999999999",
    "mediatype": "image",
    "mimetype": "image/jpeg",
    "caption": "Confira esta imagem",
    "media": "<base64 da imagem>"
  }'
```

### Enviar documento (PDF)

```bash
curl -X POST http://localhost:3100/api/message/sendMedia/meu-bot \
  -H "Content-Type: application/json" \
  -d '{
    "number": "5511999999999",
    "mediatype": "document",
    "mimetype": "application/pdf",
    "fileName": "relatorio.pdf",
    "media": "<base64 do PDF>"
  }'
```

### Enviar audio

```bash
curl -X POST http://localhost:3100/api/message/sendMedia/meu-bot \
  -H "Content-Type: application/json" \
  -d '{
    "number": "5511999999999",
    "mediatype": "audio",
    "mimetype": "audio/ogg",
    "media": "<base64 do audio>"
  }'
```

### Receber midia

Quando uma midia e recebida, o Arcanum automaticamente:
1. Faz download e descriptografa
2. Converte para base64
3. Inclui no payload do webhook no campo `media.data`

---

## Webhook

O Arcanum encaminha mensagens recebidas para a URL configurada, no formato compativel com a API Meta:

```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "gateway",
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "messages": [{
          "from": "5511999999999",
          "id": "msg_abc123",
          "timestamp": "1718900000",
          "type": "text",
          "text": {"body": "Ola!"},
          "media": {
            "mimetype": "image/jpeg",
            "data": "<base64>",
            "filename": "foto.jpg"
          }
        }]
      },
      "field": "messages"
    }]
  }]
}
```

### Seguranca

Se `GATEWAY_META_APP_SECRET` estiver definido, o Arcanum assina cada webhook com HMAC-SHA256 no header `X-Hub-Signature-256`.

### Configurar via API

```bash
curl -X POST http://localhost:3100/api/events/webhook/meu-bot \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://meu-backend.com/webhook",
    "events": ["messages", "status"],
    "enabled": true
  }'
```

---

## Configuracao

### Variaveis de ambiente

| Variavel | Padrao | Descricao |
|----------|--------|-----------|
| `GATEWAY_PORT` | 3100 | Porta HTTP |
| `GATEWAY_DB_PATH` | ./data | Diretorio para sessoes SQLite |
| `GATEWAY_WEBHOOK_FORWARD_URL` | — | URL padrao para webhooks |
| `GATEWAY_META_APP_SECRET` | — | Secret para assinar webhooks (HMAC) |

### Configuracoes por instancia

```bash
curl -X POST http://localhost:3100/api/settings/meu-bot \
  -H "Content-Type: application/json" \
  -d '{
    "rejectCalls": false,
    "groupsIgnore": true,
    "alwaysOnline": false,
    "readMessages": true,
    "readStatus": false,
    "syncFullHistory": false
  }'
```

---

## Docker

### Dockerfile

O Arcanum usa multi-stage build para gerar um binario estatico minimo:

```dockerfile
FROM golang:1.25-alpine AS builder
RUN apk add --no-cache gcc musl-dev git
WORKDIR /build
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=1 go build -o /gateway ./cmd/gateway

FROM alpine:3.20
COPY --from=builder /gateway /gateway
VOLUME /data
EXPOSE 3100
CMD ["/gateway"]
```

### Volumes

| Volume | Descricao |
|--------|-----------|
| `/data` | Sessoes SQLite (um `.db` por instancia). Persista este volume. |

---

## Exemplos de Integracao

### Python (requests)

```python
import requests

API = "http://localhost:3100"

# Criar instancia
requests.post(f"{API}/api/instance/create", json={
    "instanceName": "bot",
    "webhook": "http://meu-app:8000/webhook"
})

# Conectar
requests.get(f"{API}/api/instance/connect/bot")

# Enviar mensagem
requests.post(f"{API}/api/message/sendText/bot", json={
    "number": "5511999999999",
    "text": "Ola do Python!"
})
```

### Node.js (fetch)

```javascript
const API = 'http://localhost:3100';

await fetch(`${API}/api/instance/create`, {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({instanceName: 'bot', webhook: 'http://meu-app/webhook'})
});

await fetch(`${API}/api/instance/connect/bot`);

await fetch(`${API}/api/message/sendText/bot`, {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({number: '5511999999999', text: 'Ola do Node!'})
});
```

---

## Roadmap

- [ ] Suporte a grupos (criar, info, participantes)
- [ ] Envio de buttons e listas interativas
- [ ] Templates (Meta Business API)
- [ ] Proxy HTTP/SOCKS5 por instancia
- [ ] Labels do WhatsApp
- [ ] Business catalog
- [ ] WebSocket para eventos em tempo real
- [ ] Dashboard web
- [ ] Autenticacao por API key
- [ ] Metricas Prometheus
- [ ] Persistencia de mensagens
- [ ] Transcricao de audio embutida

---

## Stack

| Componente | Tecnologia |
|-----------|------------|
| Linguagem | Go 1.25 |
| Engine WhatsApp | [whatsmeow](https://github.com/tulir/whatsmeow) |
| HTTP Router | [Chi v5](https://github.com/go-chi/chi) |
| Sessoes | SQLite (via go-sqlite3) |
| QR Code | [go-qrcode](https://github.com/skip2/go-qrcode) |
| Container | Docker (Alpine) |

---

## Licenca

[MIT](LICENSE) — use, modifique e distribua livremente.

---

<p align="center">
  Feito com Go por <a href="https://github.com/rafaeldourado9">Rafael Dourado</a>
</p>
