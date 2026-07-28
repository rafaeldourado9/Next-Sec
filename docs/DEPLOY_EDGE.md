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

## 1. Pré-requisitos na máquina do cliente

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado
  (o instalador **não** instala isso sozinho — habilitar WSL2 pode exigir
  reboot, risco grande demais pra fazer sem supervisão humana).
- [WireGuard for Windows](https://www.wireguard.com/install/) instalado.

## 2. Onboarding do cliente (Sprint 7 — via painel admin)

Time Next Sec, logado como `admin`, em `/admin/tenants` → **"Novo Cliente
(Nível 1 — Docker)"**. Preenche nome/slug/email do gestor e o sistema cria,
numa chamada só (`POST /admin/onboard-client`):

- o tenant e o usuário gestor (**senha padrão gerada automaticamente** —
  troca obrigatória no primeiro login, ver `must_change_password`)
- a licença, já ativa (pula o fluxo manual de `POST /billing/activate`)
- o agent + túnel WireGuard (mesmo provisionamento do Nível 2 — reaproveita
  `AgentService.create_agent_with_tunnel`)

A tela mostra, **uma única vez**: a chave de licença, o email/senha padrão
do gestor, e um botão **"Baixar pacote completo (.zip)"** — contém
`nextsec.conf` (WireGuard), `.env.edge` (`VMS_API_URL`/`VMS_API_KEY` já
preenchidos) e o instalador (`docker-compose.edge.yml`, `INSTALAR.bat`,
`install-docker.ps1`, `UNINSTALAR.bat`, `uninstall-docker.ps1` — servidos
estáticos por `infra/nginx/nginx.conf`, `location /downloads/agent-docker/`,
a partir de `native_installer/windows-docker/release/`).

No hardware do cliente: extrair o `.zip` e dar duplo clique em
`INSTALAR.bat` (auto-eleva via UAC).

### O que o instalador faz

1. Confere Docker Desktop e WireGuard instalados (aborta com instrução clara se algum faltar).
2. Registra o túnel WireGuard (`nextsec-edge`).
3. Copia `docker-compose.edge.yml` + `.env.edge` pra `%ProgramData%\NextSecEdge\`.
4. Configura Docker Desktop para iniciar ao logar (via `HKCU\...\Run` — mecanismo padrão do Windows, não depende do formato interno do settings do Docker Desktop, que muda entre versões).
5. **Pergunta** se deve configurar login automático do Windows nesta máquina — com aviso de segurança explícito antes (grava a senha da conta em texto plano no registro; **só faça isso numa máquina dedicada a este agent**). Ver "Trade-off de auto-start" abaixo.
6. Registra uma Scheduled Task (`NextSecEdgeAutoStart`, trigger "At log on") que espera o Docker subir e roda `docker compose up -d`.
7. Sobe a stack imediatamente (`docker compose up -d --build`), sem esperar o próximo boot.

Para remover: `UNINSTALAR.bat` (derruba a stack, remove a Scheduled Task, o túnel, e opcionalmente reverte o login automático).

### Trade-off de auto-start (decisão consciente, não um descuido)

Docker Desktop no Windows é um app gráfico — não roda headless sem uma
sessão de usuário logada. Pra a stack subir sozinha depois de um
desligar/ligar real (sem alguém logar manualmente), a única forma prática
hoje é: login automático do Windows + Docker Desktop iniciando ao logar +
a Scheduled Task acima. O trade-off de segurança (senha em texto plano no
registro, bypass da tela de login do Windows) é real e o instalador avisa
antes de configurar — só faz sentido numa máquina 100% dedicada a este
agent, nunca num PC de uso geral do cliente.

## 3. Modo manual (dev/debug — sem o instalador)

Útil pra testar mudanças no compose sem gerar um pacote completo:

```bash
cp .env.edge.example .env.edge   # preencher VMS_API_URL/VMS_API_KEY na mão
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
túnel WireGuard). Nada a configurar aqui além do que já está no pacote de
onboarding.

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
- **Instalador Nível 1 nunca testado numa máquina Windows cliente real** —
  validado nesta sessão via parse do PowerShell + confirmação de que os
  cmdlets (`Register-ScheduledTask` etc.) existem; o registro de Scheduled
  Task/login automático de ponta a ponta ainda precisa de verificação
  manual num cliente/VM Windows de teste antes do primeiro deploy real
  (ver Sprint 7).

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

## Progresso (Sprint 7 — Onboarding por licença + instalador único Nível 1)

- [x] `must_change_password` (migration + login + `PUT /auth/change-password`)
- [x] `POST /admin/onboard-client` (tenant + gestor + licença + agent/túnel WG)
- [x] `AgentsPage.tsx` removida — criação de agent nativo (Nível 2) fica sem
      caminho de dashboard por enquanto (decisão explícita, não prioridade)
- [x] Onboarding + download do pacote em `TenantsPage.tsx` (admin)
- [x] `ForcePasswordChangeGate.tsx` — bloqueia o app até a troca de senha
- [x] `native_installer/windows-docker/` — instalador Nível 1 completo
      (Docker Desktop + WireGuard + Scheduled Task de auto-start + login
      automático opcional, com aviso de segurança)
- [x] `infra/nginx/nginx.conf` — `location /downloads/agent-docker/`
