# Deploy Edge Nível 1 (Docker dedicado no hardware do cliente)

Ver [ADR-016](../.genesis/architecture/adrs/016-edge-two-tier-deployment.md)
(por que existem dois níveis de instalação no cliente) e
[ADR-017](../.genesis/architecture/adrs/017-edge-sync-protocol.md) (o
protocolo de sincronização — evento rápido multipart + clipe assíncrono via
`PUT`).

Este nível roda no hardware do próprio cliente (mini-PC/NUC ou servidor
dedicado local) quando ele já tem uma máquina disponível na rede das
câmeras. Reempacota `mediamtx` + `analytics` + `worker` (aqui rodando
`EdgeWorkerSettings`) + um Redis local — **sem** Postgres/RabbitMQ/api/
frontend/nginx/MinIO/Arcanum locais. Toda autenticação de negócio,
notificação e storage final continuam na VPS central, acessada via túnel
WireGuard.

## 1. Pré-requisitos

- Docker + Docker Compose no hardware do cliente.
- Túnel WireGuard já configurado entre este hardware e o hub da VPS
  central (peer deste cliente já provisionado — ver `infra/wireguard/` no
  compose central).
- Tenant e API key já criados na VPS central (tabela `api_keys`) — **cada
  cliente Nível 1 tem sua própria key**, nunca reaproveitar a
  `dev-analytics-key` do `.env.example` central.

## 2. Variáveis de ambiente

Copiar `.env.edge.example` → `.env.edge` e preencher:

| Variável | Valor |
|---|---|
| `VMS_API_URL` | IP interno do hub WireGuard (sub-rede `WG_SUBNET`, default `10.60.0.0/24`) na porta da API central — **nunca** o IP público direto (porta 8000 não é exposta publicamente) |
| `VMS_API_KEY` | API key deste tenant/agente, gerada na VPS central |
| `ANALYTICS_TARGET` | `cpu` (default) ou `gpu` se o hardware do cliente tiver GPU NVIDIA + driver CUDA |
| `ANALYTICS_FPS` / `YOLO_IMGSZ` / `YOLO_CONF` / `YOLO_MODEL_PATH` | ajustar conforme hardware/câmeras deste cliente (defaults iguais ao compose central) |
| `FACE_RECOGNITION_MODEL_PATH` | vazio desabilita reconhecimento facial local (o gate de LGPD continua avaliado na VPS central) |

`.env.edge` nunca vai pro git.

## 3. Subir a stack

```bash
docker compose -f docker-compose.edge.yml --env-file .env.edge up -d --build
docker compose -f docker-compose.edge.yml ps   # todos devem ficar "healthy"
```

`analytics` fica em `starting` por até ~150s no boot normal — ele tenta
listar câmeras da VPS central antes do Uvicorn aceitar conexão (até 10
tentativas x 10s, ver `Orchestrator.start()`); o healthcheck tem
`start_period: 150s` justamente para não sinalizar isso como falha (achado
real durante S6-06 — sem essa margem, o container era marcado
`unhealthy` por um startup normal antes mesmo de existir câmera ou de o
túnel estabilizar).

## 4. Smoke test

```bash
infra/scripts/smoke-test-edge.sh
```

Sobe o stack com credenciais dummy (`VMS_API_URL`/`VMS_API_KEY` fictícios —
nenhum health check depende de a VPS central estar alcançável de verdade),
espera todos os serviços ficarem `healthy` e derruba tudo no final
(`docker compose down -v`, `trap ... EXIT`). Falha com logs se algum
serviço não subir dentro do timeout.

## 5. Câmeras

As câmeras do cliente publicam RTSP/RTMP direto para o `mediamtx` local
(portas `8554`/`1935`, mesmas do compose central). O `analytics` local lê
os frames pela rede interna do Docker (`next_sec_edge`), nunca via
internet.

`infra/mediamtx/mediamtx.yml` é um template (`authHTTPAddress` e os hooks
`runOnReady`/`runOnNotReady`/`runOnRecordSegmentComplete`) — o
`entrypoint.sh` da imagem resolve o placeholder `__VMS_HOOKS_BASE_URL__`
no start do container a partir da env `VMS_HOOKS_BASE_URL`, que este
compose já define como o mesmo valor de `VMS_API_URL` (a VPS central via o
túnel WireGuard). Nada a configurar aqui além do que já está na seção 2.

## 6. Teste E2E real (worker gera um clipe de verdade)

```bash
infra/scripts/e2e-test-edge.sh
```

Sobe a stack de verdade, escreve um snapshot JPEG real no volume
compartilhado, enfileira o job ARQ `task_render_and_upload_edge_clip` no
Redis da própria stack (o mesmo caminho que o `analytics` usa depois de um
`ingest_event` confirmado) e confirma que o worker roda **ffmpeg de
verdade** e envia um MP4 real (assinatura `ftyp`) — só a VPS central é
mockada (um servidor HTTP mínimo que recebe o `PUT .../clip`). Falha com
logs do worker/mock se o clipe não chegar dentro do timeout.

## 7. Limitações conhecidas (não resolvidas neste sprint)

- **Fila de retry (`EventOutbox`, SQLite) sem cap de tamanho/idade** —
  aceitável para o caso motivador (queda passageira de rede), mas se a VPS
  central ficar inacessível por muito tempo (horas/dias), `outbox.db` no
  volume `outbox_data` do container `analytics` cresce sem limite, sem
  aviso ou proteção de disco. Documentado com teste real em
  `analytics/tests/test_vms_client_resilience.py::TestOutboxUnboundedGrowth`
  (ver S6-06).
- **Ordem de entrega do backlog não é garantida** — sob falha concorrente
  de vários eventos, o backoff por item pode reordenar o reenvio quando a
  rede volta. Não é um bug: cada evento carrega seu próprio `occurred_at`,
  que é o que a VMS usa pra ordenar a timeline (não a ordem de chegada).
  Perda/duplicação, sim, seriam bugs reais — cobertos pelo mesmo teste
  acima.

## Progresso (Sprint 6)

- [x] S6-01 ADR-017 (protocolo de sync)
- [x] S6-02 VMSClient — fila/retry SQLite + cache last-known-good
- [x] S6-03 API — split clipe/notificação + endpoint de clipe pré-gerado
- [x] S6-04 EdgeWorkerSettings — task local de clipe
- [x] S6-05 `docker-compose.edge.yml`
- [x] S6-06 Testes edge (sync, split, compose, smoke) — 2 bugs reais achados
      e corrigidos (isolamento de tenant no `PUT .../clip`; healthcheck do
      `analytics` sem `start_period`)
- [x] S6-07 Este documento + progress/state atualizados
- [x] Pós-S6-07: `mediamtx.yml` parametrizado (era limitação conhecida) +
      `e2e-test-edge.sh` (worker gera clipe real via ffmpeg na stack viva)
