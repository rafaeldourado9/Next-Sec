# Estudo Técnico — Next Sec

> Documento de estudo científico/técnico da arquitetura do Next Sec: o que foi
> construído, como a travessia de CGNAT funciona de fato, o pipeline de
> reconhecimento facial, o que foi validado em produção real nesta sessão, e
> uma análise honesta de diferencial competitivo e de ineditismo/elegibilidade
> para fins de propriedade intelectual ou programas de incentivo.
>
> Gerado via Genesis Framework (`genesis-docs`), a partir de: `.genesis/manifest.md`,
> `.genesis/architecture/*` (ADRs 001–016, `tech-stack.md`, `reuse-plan.md`,
> `system-design.md`), `.genesis/memory/progress.md`, código-fonte real em
> `next_sec/`, e da sessão de deploy/validação em produção realizada em
> 2026-07-27/28 (VPS `2.25.180.57`, domínio `vm-server.duckdns.org`).
>
> **Atualização de 2026-07-28 (tarde):** durante essa mesma janela de
> validação em produção, um incidente real (vazamento de conexão de banco
> sob rajada de eventos, detalhado na seção 7.2-bis) expôs um limite
> estrutural da arquitetura centralizada na VPS e motivou uma mudança de
> direção (ADR-015/016: mover processamento de vídeo pro hardware do
> cliente). Este documento foi atualizado para refletir essa decisão — a
> seção 3.4 descreve a arquitetura alvo, ainda **não implementada**.
>
> **Metodologia:** cada afirmação técnica abaixo é rastreável a um arquivo de
> código, ADR, ou teste executado de fato (não é especificação aspiracional).
> Onde uma afirmação é inferência ou opinião (ex: análise de mercado,
> ineditismo), isso é sinalizado explicitamente — este projeto não tem due
> diligence jurídica ou de mercado formal por trás, é uma leitura técnica.

---

## 1. Resumo executivo

Next Sec é um sistema de segurança eletrônica (VMS — Video Management System)
orientado a **eventos e alertas**, não a exibição de vídeo ao vivo ou
gravação contínua. Ele resolve um problema de infraestrutura concreto e comum
no mercado brasileiro de CFTV residencial/comercial de pequeno porte: câmeras
atrás de **CGNAT** (Carrier-Grade NAT, padrão em conexões residenciais e boa
parte das comerciais no Brasil) não são alcançáveis diretamente pela internet,
o que historicamente força o instalador a expor portas manualmente (quando
possível) ou a depender de serviços de nuvem proprietários do fabricante da
câmera (Hikvision Hik-Connect, Dahua P2P, Intelbras Cloud, etc.), com todos os
problemas de lock-in, privacidade e confiabilidade que isso implica.

A solução implementada é um **agente de borda (edge agent)** rodando na rede
do cliente (testado nesta sessão como serviço Windows real, mas com
equivalente para Linux/embarcado no design), que:

1. Abre um túnel **WireGuard outbound** (o cliente sempre inicia a conexão —
   nunca precisa de porta aberta no roteador do cliente) para um hub
   controlado pelo Next Sec;
2. Encaminha vídeo (RTMP) e chamadas de API (heartbeat, config, WebSocket)
   através desse túnel;
3. É gerenciado dinamicamente pelo backend — cada agente novo gera um par de
   chaves WireGuard único, registrado como peer no hub via uma API de
   controle própria (não é configuração estática).

Sobre essa fundação, o produto adiciona: reconhecimento facial local (rodando
em CPU, sem depender de nuvem de terceiros para biometria), cercamento
virtual com agendamento por horário, alertas via WhatsApp usando um gateway
próprio self-hosted (não a API paga da Meta), e um fluxo de compliance LGPD
(gate de consentimento) embutido no produto desde o início — não como
retrofit.

**O que foi validado nesta sessão (não é só design em papel):** deploy real
numa VPS de produção compartilhada, emissão de certificado TLS real, criação
de tenant/usuário/licença reais, e — o teste mais importante — **um agente
Windows real, rodando numa rede doméstica/comercial real, atravessando CGNAT
de fato e estabelecendo handshake WireGuard com o hub**, confirmado via
`wg show` no servidor (`latest handshake: 41 seconds ago`, tráfego real
transitando nos dois sentidos). Isso não é uma simulação — é o mecanismo
central do produto, testado ponta a ponta.

---

## 2. Origem e contexto: por que existe reaproveitamento

O Next Sec **não** foi escrito do zero. Ele nasce de um projeto anterior,
`vms/`, que por sua vez nasceu de engenharia reversa de um VMS comercial de
referência (CluebaseVMS/vCloud.ai) — mosaico ao vivo, gravação contínua,
VOD, analíticos pesados (LPR, PPE, contagem de pessoas/veículos, fogo/fumaça,
etc.), faturamento (billing/GMV). O `vms/` é maior e mais genérico do que o
Next Sec precisa.

A decisão de arquitetura (ADR-013) foi criar um **projeto novo e isolado**
(`next_sec/`), semeado com uma cópia seletiva do que já existia e validado no
`vms/`, em vez de (a) reescrever do zero, ou (b) adicionar a feature dentro do
`vms/` in-place. O `vms/` original permanece intocado.

Isso importa para o estudo porque explica uma característica real do código:
**parte significativa do sistema é reaproveitamento deliberado e documentado,
não invenção nova.** Isso é relevante tanto para o entendimento técnico
quanto — mais adiante — para a análise honesta de ineditismo (seção 8):
Postgres, FastAPI, Redis, RabbitMQ, React, JWT, MediaMTX e o próprio conceito
de "VMS com plugins de analítico" já existiam prontos e testados antes deste
projeto. O que é novo está listado explicitamente na seção 4 do
`reuse-plan.md` ("Gaps reais") e resumido na seção 7 deste documento.

---

## 3. Arquitetura geral

### 3.1 Visão de componentes (C4 nível 2, resumido)

> **Nota:** o diagrama abaixo descreve a arquitetura **atual** do piloto
> (processamento de vídeo centralizado na VPS). A seção 3.4 documenta por
> que isso se mostrou insustentável na prática e a direção de arquitetura
> aprovada (ainda não implementada) pra resolver isso.

```
┌─────────────────────┐         WireGuard UDP 51820          ┌──────────────────────────────────┐
│   Rede do cliente    │ ─────────(túnel outbound)──────────▶ │        VPS (2 vCPU / 8GB,         │
│                      │                                       │    compartilhada com FastOS/Civix) │
│  ┌────────────────┐  │                                       │                                    │
│  │  Câmera RTSP    │  │                                       │  ┌──────────────────────────────┐  │
│  │  (bullet, CGNAT)│  │                                       │  │ nginx (FastOS, compartilhado) │  │
│  └────────┬───────┘  │                                       │  │  80/443 · TLS termina aqui    │  │
│           │RTSP       │                                       │  └──────────────┬───────────────┘  │
│  ┌────────▼───────┐  │                                       │                  │ proxy_pass         │
│  │  Edge Agent     │──┼── RTMP push + WS/HTTP ───────────────▶│  ┌──────────────▼───────────────┐  │
│  │  (Windows svc,  │  │      via túnel wg0                    │  │  nginx (Next Sec, rede         │  │
│  │  NSSM + WG)     │  │                                       │  │  interna) → api / frontend    │  │
│  └─────────────────┘  │                                       │  └──────────────┬───────────────┘  │
└──────────────────────┘                                       │                  │                   │
                                                                 │  ┌──────────────▼───────────────┐  │
                                                                 │  │  api (FastAPI) ── iam, cameras,│  │
                                                                 │  │  events, plugins, notifications,│  │
                                                                 │  │  lgpd, audit, watchlist, billing│  │
                                                                 │  └───┬──────────┬──────────┬─────┘  │
                                                                 │      │          │          │         │
                                                                 │  ┌───▼───┐ ┌───▼────┐ ┌───▼──────┐  │
                                                                 │  │Postgres│ │RabbitMQ│ │  Redis   │  │
                                                                 │  └───────┘ └───┬────┘ └──────────┘  │
                                                                 │                │                     │
                                                                 │  ┌─────────────▼─────────────────┐  │
                                                                 │  │ analytics (YOLOv8 + InsightFace│  │
                                                                 │  │  buffalo_s, CPU) — lê RTSP do  │  │
                                                                 │  │  MediaMTX, publica eventos     │  │
                                                                 │  └─────────────┬───────────────┘  │
                                                                 │                │                    │
                                                                 │  ┌─────────────▼───────────────┐  │
                                                                 │  │  MinIO (clipe/frame) · MediaMTX│  │
                                                                 │  │  Arcanum (WhatsApp gateway)     │  │
                                                                 │  └──────────────────────────────┘  │
                                                                 └────────────────────────────────────┘
```

### 3.2 Estilo arquitetural (ADR-007)

**Modular monolith** no `api/` (bounded contexts como pastas Python
separadas — `iam`, `cameras`, `events`, `plugins`, `notifications`, `lgpd`,
`audit`, `watchlist`, `billing`, `admin` — dentro de um único processo/deploy),
com **serviços satélite** verdadeiramente separados onde há uma razão
concreta para isolamento de processo:

| Serviço | Por que é separado |
|---|---|
| `analytics/` | Carga de CPU de inferência de vídeo (YOLO + InsightFace) — isolar do processo da API evita que picos de inferência degradem latência de requisições HTTP normais |
| `edge_agent/` | Roda fisicamente **fora** da VPS, na rede do cliente — não é uma opção arquitetural, é uma necessidade física |
| `wireguard` (hub) | Precisa de `NET_ADMIN`/acesso a interface de rede — isolar reduz superfície de ataque do resto do sistema |
| `arcanum` | Gateway WhatsApp de terceiros (projeto próprio, Go), consumido via API REST — desacoplado por natureza |

Isso não é microsserviços "porque é moderno" — é a aplicação prática da
regra de tier (ADR-011): a escala do projeto (dezenas de câmeras, um piloto)
não justificaria essa separação do zero, mas cada um dos quatro serviços
acima tem uma razão técnica concreta (não organizacional) para existir
isolado, então a exceção é justificada caso a caso, não por padrão.

### 3.3 Stack (resumo — detalhamento e justificativa por item em `tech-stack.md`)

| Camada | Tecnologia | Origem |
|---|---|---|
| Backend | Python 3.12 + FastAPI | Reaproveitado do `vms/` |
| Banco | PostgreSQL 16 | Reaproveitado, multi-tenant nativo |
| Cache | Redis 7 | Reaproveitado (SSE pub/sub, dedup, cache de ROI) |
| Message broker | RabbitMQ 3 | Reaproveitado (event bus dos eventos de analítico) |
| Object storage | MinIO self-hosted (VPS) | Adaptado (Google Drive foi avaliado e adiado) |
| Analítico de vídeo | YOLOv8 (Ultralytics) + InsightFace `buffalo_s` | Framework de plugins reaproveitado; InsightFace é integração nova (ADR-014) |
| Canal de notificação | WhatsApp via Arcanum (gateway próprio, Go, `whatsmeow`) | Integração nova (ADR-009) |
| Frontend | React 18 + TypeScript + Vite | Reaproveitado, com remoção de escopo (mosaico, gravação, VOD, billing pesado) |
| Ingestão de mídia | MediaMTX (RTSP↔RTMP↔HLS) | Reaproveitado |
| Edge agent | Python (PyInstaller → `.exe` no Windows) | Reaproveitado + túnel WireGuard novo |
| Deploy | Docker Compose numa VPS compartilhada (2 vCPU/8GB) | ADR-005 |

### 3.4 Limite estrutural identificado e arquitetura alvo (ADR-015/016)

**O que aconteceu de verdade (2026-07-28):** horas depois do primeiro
deploy piloto (Sprint 5), a VPS compartilhada sofreu um incidente de
produção real — `load average` chegou a **151**, depois **171** num
segundo episódio no mesmo dia, memória e swap saturados, `502 Bad
Gateway` na API, afetando também FastOS/Civix (vizinhos na mesma VPS).
Dois bugs de código foram encontrados e corrigidos (commits `c3efe4d` e
`c1ae985` — sessões de banco assíncronas compartilhadas indevidamente
entre corrotinas concorrentes, ver seção 7.2-bis para o detalhamento
completo). **Mas o segundo episódio aconteceu mesmo depois dos dois
fixes de código**, só com uma rajada real de eventos gerando clipes via
`ffmpeg` concorrentemente — a conclusão técnica é que **o problema não
é (só) bug, é estrutural**: inferência de vídeo (YOLO/InsightFace) e
geração de clipe (`ffmpeg`) são cargas de CPU pesadas e contínuas que não
cabem numa VPS de 2 vCPU compartilhada com outros dois produtos, não
importa quão bem o código trate concorrência.

**Decisão (ADR-015, estendida pela ADR-016):** mover o processamento de
vídeo (streaming/ingestão, inferência, geração de clipe) para o hardware
do cliente, deixando a VPS restrita ao papel de **plano de controle
multi-tenant**: persistência (Postgres), exibição (dashboard/API),
armazenamento do clipe já pronto (MinIO), gestão (tenants, usuários,
regras) e relatórios. Concretamente, um modelo de **dois níveis** de
instalação no cliente, escolhido no momento da instalação:

1. **Nível 1 — Docker dedicado:** quando existe uma máquina própria
   (mini-PC/NUC) no local do cliente, ela roda os mesmos containers que
   hoje rodam na VPS (`mediamtx`, `analytics`, `worker`) via um
   `docker-compose.edge.yml` próprio — reaproveitamento direto de código
   já testado, sem reescrever a lógica de inferência/clipe. Só o evento
   final (já com clipe gerado e enviado) sincroniza com a VPS central.
2. **Nível 2 — Agent nativo embutido:** quando a máquina do cliente é o
   PC comum dele (não dá pra exigir Docker sem fricção real de
   instalação — confirmado que isso varia de cliente pra cliente), a
   inferência é embutida diretamente no executável nativo do
   `edge_agent/` (PyInstaller), com detecção automática de GPU/CPU —
   plano original da ADR-015.
3. **Nível 3 — VPS centralizada (fallback):** o que existe hoje. Deixa
   de ser o caminho default e vira plano B explícito, só pra clientes
   ainda não migrados ou sem hardware suficiente pros níveis 1/2.

**Estado real em 2026-07-28:** a decisão está documentada (ADR-016), a
implementação **ainda não começou**. Como mitigação temporária até essa
migração, a geração de clipe foi colocada atrás de uma flag
(`ENABLE_EVENT_CLIPS=false` em produção) — o pipeline de notificação
(WhatsApp com foto do snapshot + texto) continua funcionando
normalmente, só a geração do vídeo via `ffmpeg` (a parte que sobrecarrega
a CPU) está temporariamente desativada na VPS. Ver `ADR-015` e `ADR-016`
para o racional completo, alternativas consideradas e escopo de
implementação.

---

## 4. A travessia de CGNAT — como funciona de fato

Esta é a peça de engenharia mais importante do produto do ponto de vista de
infraestrutura, então merece o detalhamento completo.

### 4.1 O problema

CGNAT (Carrier-Grade NAT) significa que o roteador do cliente **não tem um IP
público próprio** — ele está atrás de um NAT operado pela operadora,
compartilhado com outros clientes. Isso torna port-forwarding tradicional
**impossível** na prática (o cliente não controla o NAT da operadora). Câmeras
IP genéricas expostas via RTSP direto simplesmente não são alcançáveis de
fora dessa rede.

Isso é bastante comum no Brasil, principalmente em conexões residenciais e em
provedores regionais/locais.

### 4.2 A solução: túnel outbound + hub controlado pelo backend

A solução **não** depende de a câmera ou o roteador do cliente terem IP
público, e **não** depende de configuração manual de porta pelo cliente ou
instalador. O princípio é: **a conexão é sempre iniciada de dentro para
fora** — CGNAT nunca bloqueia conexões outbound, só inbound não solicitadas.

**Peças reais do mecanismo** (todas testadas nesta sessão, não apenas lidas
no código):

1. **Hub WireGuard** (`infra/wireguard/`, container `wireguard` no
   `docker-compose.yml`, linha 89 em diante) — roda na VPS, escuta
   `51820/udp`. Publica a porta diretamente no host; o Docker moderno
   gerencia a liberação de firewall automaticamente ao publicar a porta (não
   depende de `ufw` nem de configuração manual de iptables — verificado
   nesta sessão via `iptables -L DOCKER` e `ss -ulnp`).

2. **Chave do hub é persistida, não efêmera** (`entrypoint.sh`, linhas 15–23)
   — gerada uma vez (`wg genkey`) e salva em volume; se fosse regenerada a
   cada restart do container, **todo peer já provisionado ficaria órfão**
   (a confiança do lado do agente é fixada na chave pública do hub, gravada
   no `nextsec.conf` de cada cliente).

3. **Peers são dinâmicos, não estáticos** — o `wg0.conf` do hub **não contém
   nenhum `[Peer]`** escrito estaticamente. Peers são adicionados e removidos
   em tempo real via `wg set` (comando `_add_peer`/`_remove_peer` em
   `control_api.py`), chamado por uma API HTTP de controle própria
   (autenticada por `WG_CONTROL_TOKEN`), que por sua vez é chamada pela API
   principal (`api/src/vms/cameras/wireguard_client.py`) sempre que um
   usuário cria ou remove um agent pelo dashboard. **Cada agente novo recebe
   um par de chaves WireGuard único**, gerado no momento da criação, nunca
   reaproveitado.

4. **A chave privada do agente é mostrada uma única vez** — o backend
   explicitamente **não persiste** a chave privada gerada para cada agente
   (`router.py`, comentário: *"a chave privada do túnel nunca é persistida"*)
   depois de devolvida na resposta de criação. Isso significa que, se o
   pacote de instalação for perdido, não existe forma de "reemitir" as
   credenciais — é preciso criar um agente novo (mesma garantia de segurança
   de uma API key exibida uma vez só). **Isso não é uma limitação
   acidental — foi um problema real encontrado e diagnosticado nesta sessão**
   (um pacote de instalação antigo, de um agente já apagado do banco, não
   conseguia autenticar — o diagnóstico envolveu comparar o `AGENT_ID` do
   `config.env` local contra a tabela `agent_tunnels` no Postgres e o `wg
   show` do hub, encontrando a raiz real do problema).

5. **Reconciliação na inicialização** — ao subir, o hub lê o estado real dos
   agentes no Postgres (via API) e reaplica os peers esperados
   (`reconcile_from_api()`), com retry (5 tentativas, 3s de intervalo) caso a
   API ainda não esteja de pé. Isso significa que o hub não depende de o
   volume WireGuard "lembrar" os peers entre deploys — a fonte de verdade é
   o banco, não o estado local do container.

6. **Superfície de rede minimizada por design** — o hub **não** roteia o
   tráfego do túnel livremente para toda a rede Docker. Ele encaminha
   (`socat`) **apenas duas portas específicas**, amarradas ao IP do próprio
   `wg0` (nunca `0.0.0.0`): a API (`8000`, para heartbeat/config/WebSocket) e
   o RTMP do MediaMTX (`1935`, para o vídeo). Nenhum outro serviço do
   `docker-compose.yml` (Postgres, Redis, RabbitMQ, MinIO) é alcançável
   através do túnel, mesmo que um peer malicioso tentasse. Isso é uma
   decisão de segurança explícita, comentada no próprio `entrypoint.sh`.

7. **`AllowedIPs` restrito no lado do cliente** — o `nextsec.conf` gerado
   para cada agente tem `AllowedIPs = 10.60.0.1/32` (só o hub, /32) — o
   agente não enxerga nem tenta rotear tráfego para outros peers/clientes
   através do túnel. Cada cliente é isolado dos demais na camada de rede,
   não só na camada de aplicação (tenant_id).

### 4.3 O que foi validado de verdade nesta sessão (não é design teórico)

Isso foi testado com um agente Windows real, numa máquina real, contra o hub
de produção real:

```
# No hub (VPS), depois da instalação do agente:
$ wg show
interface: wg0
  public key: zNKoBturqkithYQam/8mNoIUOApi2h+C3cRA6plrAFY=
  listening port: 51820

peer: awSu00pjQNUsQuq3JBbHAT9DUJupzj+kgQMutiDmnzY=
  endpoint: 170.238.249.81:42563        ← IP público real do cliente, CGNAT
  allowed ips: 10.60.0.5/32
  latest handshake: 41 seconds ago
  transfer: 5.99 KiB received, 5.89 KiB sent
```

E do lado do agente, os logs reais mostraram o ciclo completo funcionando:
`GET /api/v1/agents/me/config` → `200 OK`, `POST /api/v1/agents/me/heartbeat`
→ `200 OK`, WebSocket conectado. O agente ficou marcado `online` no banco
(`agents.status`, `last_heartbeat_at` atualizado).

**Isso é a prova de que a técnica funciona em condições reais**, não apenas
em ambiente controlado — o cliente de teste estava numa rede doméstica/
comercial comum, sem qualquer configuração manual de roteador.

### 4.4 O que essa técnica é, tecnicamente falando (honestidade sobre ineditismo)

O padrão "hub-and-spoke WireGuard com provisionamento dinâmico de peers via
API" **não é uma invenção do Next Sec** — é a mesma ideia central de
produtos consolidados como **Tailscale**, **ZeroTier**, **Nebula** (Slack) e
**Netmaker**: uma rede overlay onde um coordenador central provisiona chaves
e peers, e os nós conectam outbound para atravessar NAT. WireGuard em si é
um protocolo público (RFC-adjacent, código aberto, mantido pela comunidade
Linux/kernel).

**O que existe aqui de fato próprio** é a **integração vertical**: o
provisionamento do túnel está acoplado ao ciclo de vida do domínio de
negócio (criar um "Agent" no Next Sec cria o peer WireGuard atomicamente,
apagar o Agent remove o peer, o hub só expõe as duas portas do próprio
produto) — não é "instale um Tailscale e depois configure o VMS por cima",
é uma peça só, desenhada para esse produto específico. Isso é engenharia de
integração sólida e é um diferencial de *produto* (menos passos de setup
para o cliente final, sem depender de outra conta/serviço de terceiros), mas
**não é uma técnica de rede nova o suficiente para ser patenteável por si
só** — ver seção 8 para a análise completa.

---

## 5. Fluxo completo de um evento (ponta a ponta)

1. **Captura:** a câmera RTSP do cliente é lida pelo `edge_agent` (que
   também pode consumir de câmeras ONVIF/ISAPI, herdado do `vms/`) e
   reencaminhada via **RTMP push** através do túnel WireGuard para o
   `MediaMTX` na VPS (`rtmp://10.60.0.1:1935`, roteado pelo `socat` do hub).
2. **Leitura pelo analytics:** o serviço `analytics/` lê o RTSP do MediaMTX
   (não do agente diretamente) a `ANALYTICS_FPS=1` (1 frame/segundo — decisão
   deliberada de custo de CPU, ADR-012) e roda os plugins ativos:
   - `intrusion` — cercamento virtual (ROI poligonal) + agendamento por
     horário (`is_armed_now()`, fuso `America/Sao_Paulo` fixo — corrigido
     nesta sessão de desenvolvimento, o código original comparava contra UTC);
   - reconhecimento facial **não roda mais continuamente** — foi
     redesenhado (ver seção 6) para busca sob demanda.
3. **Publicação do evento:** ao detectar um cruzamento, o `analytics`
   publica via `VMSClient.ingest_event` → `POST /api/v1/plugins/events`,
   persistido em `vms_events` (uma de três tabelas de evento herdadas do
   `vms/`, nunca consolidadas — ver observação na seção 7.2) e propagado
   como evento de domínio no RabbitMQ.
4. **Clipe:** um clipe curto (freeze-frame via ffmpeg, v1 sem ring-buffer —
   documentado como limitação conhecida) é gerado e salvo no MinIO via o
   `StorageProvider` adapter.
5. **Notificação:** o `Dispatcher` (`notifications/dispatcher.py`) resolve o
   contato cadastrado para aquela câmera/regra e despacha via `ChannelAdapter`
   — hoje, WhatsApp via Arcanum (`sendMedia`, imagem com a caixa delimitadora
   desenhada na detecção).

Cada uma dessas etapas foi testada de forma real nesta sessão de
desenvolvimento contra uma câmera física (não apenas com dados sintéticos) —
ver os "achados" documentados na seção 7.3, que incluem bugs reais de
produção encontrados e corrigidos durante esse teste (polígono de ROI
corrompido, matching de tracking instável a baixo FPS, timezone errado no
agendamento, entre outros).

> **Nota (2026-07-28):** os passos 2 (leitura pelo `analytics`) e 4
> (geração de clipe) são exatamente os que a ADR-015/016 planeja mover
> pro hardware do cliente (seção 3.4) — hoje ainda rodam centralizados na
> VPS, e o passo 4 está temporariamente desativado em produção
> (`ENABLE_EVENT_CLIPS=false`) depois do incidente descrito na seção
> 7.2-bis.

---

## 6. Reconhecimento facial — decisão e pipeline real

### 6.1 Biblioteca: InsightFace `buffalo_s` (ADR-014)

Comparado formalmente contra `face_recognition` (dlib) e `DeepFace`. Vencedor
por ser o único que (a) instala sem compilar toolchain nativo pesado e (b)
tem uma variante "small" pensada para CPU — a VPS de produção não tem GPU e é
compartilhada com outros dois sistemas (FastOS, Civix).

**Validado de ponta a ponta nesta sessão** (não é só escolha em papel):
build da imagem Docker, download real do modelo (~124MB via GitHub
releases), carregamento dos 5 sub-modelos ONNX via `CPUExecutionProvider`,
detecção real (6 rostos numa imagem de teste), embedding de 512 dimensões
corretamente normalizado (norma L2 = 1.0), similaridade de cosseno entre
pessoas diferentes = 0.048 (corretamente baixa).

### 6.2 Decisão de produto: busca sob demanda, não inferência contínua

Uma decisão importante, tomada **durante teste local com o produto real**
(não na fase de arquitetura original): rodar InsightFace em todo frame de
toda câmera continuamente (como o `intrusion` faz) não fazia sentido de
produto nem de custo de CPU. O fluxo final é:

1. Cliente cadastra um rosto na Watchlist (`POST /watchlist/faces`);
2. Cliente aciona uma busca pontual (botão "Buscar") que varre os *snapshots*
   de eventos já existentes (gerados pelo `intrusion`) tentando encontrar
   aquele rosto — sem rodar inferência facial em tempo real;
3. Isso é implementado em `analytics/core/face_search.py` (singleton lazy,
   não carrega o modelo no startup do serviço) e exposto via
   `POST /watchlist/faces/{id}/search`.

Essa mudança de "reconhecimento facial contínuo" para "busca sob demanda" é
uma decisão de produto **e** de engenharia de custo (evita rodar um modelo de
CPU pesado em todo frame de toda câmera, numa VPS compartilhada de 2 vCPU) —
vale destacar na análise de diferencial (seção 7.4) e na de ineditismo
(seção 8), pois é uma escolha deliberada, documentada, e testada — não um
acidente de implementação.

### 6.3 Gate de LGPD

O reconhecimento facial só é ativado por tenant após consentimento explícito
(`POST /lgpd/consent` liga `tenant.facial_recognition_enabled`). Esse gate
existia no código copiado mas **estava desconectado** — nunca era de fato
ativado por nenhum fluxo (bug real, corrigido no Sprint 3). Hoje é
funcional e é parte do pipeline, não um formulário decorativo.

---

## 7. O que foi construído — mapeamento honesto por sprint

> Fonte: `.genesis/memory/progress.md` e `.genesis/architecture/reuse-plan.md`,
> ambos atualizados durante a execução real (não retroativamente).

### 7.1 Linha do tempo

| Sprint | Escopo | Status |
|---|---|---|
| 1 — Fundação | Git init, `.env`, migration baseline (escrita à mão, sem autogenerate), smoke test real (`docker compose up`, upgrade/downgrade/upgrade roundtrip) | ✅ Concluído — achou e corrigiu um bug real de import (`event_registry` não exportado) |
| 2 — Contatos + horário de zona | CRUD de contatos (E.164), CRUD de `roi_schedules`, lógica "zona armada agora?" (cruzamento de meia-noite testado), 19 testes reais em container | ✅ Concluído |
| 3 — Watchlist/reconhecimento facial | CRUD `face_profiles`, embedding real (InsightFace), matching por similaridade, gate de LGPD, 31 testes reais | ✅ Concluído — corrigiu o gate de LGPD nunca ativado e o agendamento de horário nunca filtrando de fato a inferência |
| 4 — Storage & canal | `MinIOStorageProvider`, geração de clipe (ffmpeg), `ChannelAdapter` Arcanum, dispatcher, retenção/limpeza automática de clipes, 17 testes novos (41 total) | ✅ Concluído — descobriu três tabelas de evento paralelas nunca consolidadas (ver 7.2) |
| 5 — Deploy piloto | Deploy real na VPS compartilhada, DNS, TLS, pareamento de agente Windows, seed de tenant/licença, ONVIF discovery, ledger de webhook, **incidente de produção real + mudança de arquitetura (ver 7.2-bis)** | 🔄 Em andamento — deploy, TLS e pareamento do agente concluídos; incidente de produção diagnosticado e mitigado (não resolvido na raiz — a raiz é a arquitetura em si, ver ADR-016); pendente: migração de dois níveis, canal WhatsApp pareado, câmera real cadastrada, teste E2E completo |

### 7.2 Dívida técnica conhecida e documentada (não escondida)

Estes itens são deliberadamente listados aqui porque um estudo técnico
honesto não omite dívida técnica real:

- **Três tabelas de evento paralelas** (`vms_events`, `analytic_events`,
  `analytics_events`) herdadas do `vms/`, nunca consolidadas. Apenas
  `vms_events` é o caminho real usado pelo pipeline de `intrusion`/
  `face_recognition` hoje — as outras duas são vestígio de features
  removidas (busca de vídeo, dashboard antigo).
- **Clipe de evento é freeze-frame (v1), não um clipe de vídeo real** —
  documentado explicitamente como limitação a evoluir para ring-buffer.
- **Instabilidade de firmware de câmera real via RTSP-sobre-TCP** —
  encontrada durante teste com câmera física; câmera reconecta a cada ~15s;
  mitigado (reconexão mais rápida, `sourceProtocol: tcp`) mas não resolvido
  na raiz (depende de firmware do fabricante ou de usar a substream).
- **Renovação do certificado TLS do domínio DuckDNS é manual** — o script
  automático de renovação do FastOS (`renew-ssl.sh`) usa desafio DNS-01 via
  Cloudflare, que não serve para domínios DuckDNS; o certificado do Next Sec
  foi emitido via HTTP-01/webroot nesta sessão e precisa de renovação manual
  a cada ~80 dias até que isso seja automatizado.

### 7.2-bis Incidente de produção real (2026-07-28) — causa raiz e mudança de arquitetura

Este é o achado mais significativo da sessão do ponto de vista de
arquitetura, então merece registro detalhado (é o gatilho direto da
ADR-015/016, seção 3.4).

**Sintoma:** horas após o deploy do Sprint 5, a VPS apresentou `load
average` de **151**, memória e swap (4GB) praticamente saturados,
`next_sec-worker-1` com healthcheck falhando, `GET /api/v1/events`
retornando `502`. Por ser VPS compartilhada, isso também degradou
FastOS/Civix.

**Causa raiz #1 (corrigida, commit `c3efe4d`):** em
`notifications/service.py::evaluate_and_dispatch`, quando 2+ regras de
notificação (`destination_type=contact`) casavam com o mesmo evento, um
`asyncio.gather` rodava múltiplos `await self._contacts.get_by_id(...)`
concorrentemente — todos usando a **mesma `AsyncSession`** (SQLAlchemy
async não suporta isso). As conexões ficavam presas em `idle in
transaction` para sempre, esgotando o pool de conexões do worker (10 no
total). Fix: resolver os contatos sequencialmente antes do `gather`.

**Causa raiz #2 (corrigida, commit `c1ae985`), encontrada minutos
depois do deploy do fix #1:** o mesmo padrão existia em
`event_clips/service.py::generate_and_upload` — a sessão de banco ficava
aberta durante **todo** o render via `ffmpeg` e o upload pro storage
(ambos lentos, sem relação nenhuma com banco). Sob uma rajada de eventos
reais (`analytics.speed.measured`), isso empilhou conexões presas de
novo. Fix: cada atualização de status passou a usar uma sessão própria,
curta, commitada e fechada na hora — a sessão principal não fica mais
presa durante o trabalho pesado. `max_jobs` do worker ARQ também foi
reduzido de 50 para 10, alinhando com o tamanho real do pool de conexões.

**O achado mais importante — o incidente se repetiu mesmo depois dos
dois fixes:** com o código corrigido e a concorrência limitada, uma
nova rajada de eventos reais fez o `load average` bater **171** (pior
que o pico original), com uma dezena de processos `ffmpeg` concorrentes
consumindo centenas de MB de RAM cada, num host de 2 vCPU / 8GB. Isso
foi decisivo: **não era (só) um bug de concorrência de banco — é que
inferência de vídeo e encoding via `ffmpeg`, mesmo bem escritos e bem
limitados, são cargas de CPU/memória incompatíveis com uma VPS
pequena e compartilhada rodando várias câmeras.** Essa evidência
motivou diretamente a ADR-015 (mover inferência pro edge) e sua extensão,
a ADR-016 (modelo de dois níveis: Docker dedicado no cliente ou agent
nativo embutido, com a VPS central virando fallback, não default).

**Mitigação em produção até a migração ser implementada:** o worker foi
temporariamente parado e religado com a geração de clipe desativada via
flag (`ENABLE_EVENT_CLIPS=false`, commit `808f04f`) — o pipeline de
notificação (foto + texto via WhatsApp) continua funcional, só o
`ffmpeg` (parte cara) está pausado.

Isso é um exemplo real (não hipotético) de um limite arquitetural sendo
descoberto por evidência empírica em produção, não por análise teórica
antecipada — e da decisão de arquitetura sendo revisada em resposta a
essa evidência, dentro do mesmo dia.

### 7.3 Bugs reais encontrados e corrigidos durante testes com dados reais

Uma característica notável deste projeto é que boa parte da correção de
bugs não veio de code review, veio de **testar contra câmera real e
observar o comportamento errado**:

- ROI com polígono auto-intersectante (bug de UI que duplicava pontos)
  fazia o `_point_in_polygon` nunca detectar cruzamentos corretamente;
- Tracking entre frames a 1 FPS estava mal calibrado (peso de IoU vs.
  distância), fazendo cada frame virar um "track" novo e nunca disparar
  evento de cruzamento;
- Agendamento de horário comparava contra UTC, não horário local
  (`America/Sao_Paulo`), desarmando/armando a zona ~3h fora do horário
  configurado pelo cliente;
- Player HLS em loop de erro 401 por causa de cookies `Secure` num ambiente
  sem TLS ponta a ponta;
- SSE de eventos sempre 401 por ler uma chave de `localStorage` que nunca
  existiu.

Isso é relevante para o estudo porque mostra que a validação do produto não
foi apenas "roda em ambiente de dev" — envolveu depuração de comportamento
real de câmera, rede e fuso horário.

---

## 8. Diferencial competitivo

Comparação honesta contra as categorias de concorrência reais:

| Categoria de concorrente | Exemplo | Onde o Next Sec é diferente |
|---|---|---|
| **Nuvem proprietária do fabricante** | Hik-Connect (Hikvision), Dahua P2P, Intelbras Cloud | Essas soluções resolvem CGNAT com um relay P2P fechado do fabricante — o cliente fica preso ao ecossistema daquela marca de câmera, sem controle sobre onde o vídeo/dado trafega. O Next Sec é agnóstico de marca de câmera (RTSP/ONVIF/ISAPI genérico) e o túnel é operado pelo próprio operador do sistema, não por um terceiro fabricante |
| **VMS on-premise tradicional** | Milestone, Digifort, iVMS local | Exigem que o cliente (ou instalador) resolva CGNAT por conta própria (VPN manual, DDNS + port-forward) — não é um problema que o produto resolve, é responsabilidade do cliente. O Next Sec entrega isso pronto, sem intervenção manual de rede |
| **Plataformas de nuvem genéricas de câmera** | Verkada, Eagle Eye, Ubiquiti Protect Cloud | Essas são fortes tecnicamente, mas são SaaS fechado (dados na nuvem do fornecedor, custo recorrente por câmera geralmente alto, sem opção de self-host). O Next Sec é self-hosted por design (a VPS é do operador, os dados não saem para um terceiro) — mais próximo do que uma pequena operadora/integrador brasileiro consegue efetivamente vender e controlar |
| **Alertas via SMS/App proprietário** | Maioria dos DVRs/NVRs comerciais | O Next Sec usa WhatsApp — canal que o cliente final brasileiro já usa e confia, via um gateway self-hosted (Arcanum) em vez de depender da API paga da Meta (custo por conversa) ou de SMS (custo por mensagem, menos engajamento) |

**Resumindo o diferencial em uma frase honesta:** o Next Sec não inventa uma
tecnologia nova — ele **combina** travessia de CGNAT sem configuração manual,
reconhecimento facial local (sem enviar biometria para nuvem de terceiros),
alerta via canal que o público brasileiro já usa, e um modelo de deploy
self-hosted de baixo custo (VPS compartilhada), numa oferta que hoje exigiria
escolher entre várias soluções fechadas e caras, ou montar manualmente com
ferramentas soltas (VPN + VMS + script de alerta). O valor está na
integração e no custo operacional baixo, não numa técnica isolada nova.

---

## 9. Ineditismo e elegibilidade — análise honesta

> **Aviso:** isto é uma leitura técnica, não um parecer jurídico. Para
> qualquer decisão real de propriedade intelectual (patente, registro de
> software) ou de elegibilidade a programas de incentivo fiscal (Lei do Bem,
> Lei da Informática, editais FINEP/FAPESP, Sebrae, etc.), é necessário
> consultar um advogado especializado em propriedade intelectual e/ou um
> contador especializado em incentivos à inovação. O que segue é uma
> avaliação técnica de honestidade sobre o que é ou não original.

### 9.1 O que **não** é patenteável/inédito (e por quê)

- **WireGuard hub-and-spoke para travessia de NAT** — técnica de rede
  amplamente conhecida e implementada por múltiplos produtos comerciais
  (Tailscale, ZeroTier, Nebula, Netmaker) e mesmo por tutoriais públicos de
  WireGuard. Não há passo inventivo aqui — é aplicação de uma técnica
  conhecida a um domínio de negócio.
- **YOLO para detecção de objetos/pessoas** — biblioteca de terceiros
  (Ultralytics), uso padrão de mercado para esse tipo de aplicação.
- **InsightFace para reconhecimento facial** — biblioteca de terceiros,
  mesma observação.
- **Cercamento virtual (linha/área de detecção com polígono)** — conceito
  padrão de mercado em qualquer VMS com analítico de vídeo há mais de uma
  década.
- **Alertas via WhatsApp para eventos de segurança** — já oferecido por
  diversos produtos de CFTV/alarme no Brasil (mesmo que via integrações de
  terceiros como Twilio/Meta API, o conceito de produto não é novo).
- **Arquitetura de plugins para analíticos de vídeo** — padrão comum em VMS
  comerciais (o próprio projeto de referência que inspirou o `vms/` original
  já tinha isso).

Combinar técnicas conhecidas de formas conhecidas **não** costuma superar o
critério de "passo inventivo não óbvio" exigido para patente (no Brasil,
regido pela Lei da Propriedade Industrial, Lei 9.279/96, art. 8º — novidade,
atividade inventiva e aplicação industrial). Um examinador de patentes
provavelmente classificaria o conjunto acima como "estado da técnica" +
"combinação óbvia para um técnico no assunto".

### 9.2 O que **pode** ter algum valor de propriedade intelectual (com ressalvas)

- **A integração específica e o fluxo de provisionamento** (criar um "Agent"
  no produto atomicamente cria/destrói o peer WireGuard, com chave exibida
  uma única vez, reconciliação automática a partir do banco, superfície de
  rede restrita a duas portas por `socat`) é uma implementação específica e
  bem documentada, mas — sendo honesto — é **know-how de engenharia e
  possivelmente segredo industrial (trade secret)**, não matéria patenteável
  por si só. O valor de proteção mais realista aqui é **direito autoral
  sobre o código-fonte** (automático no Brasil, Lei 9.609/98 — Lei do
  Software) e **sigilo/contrato** (NDA com colaboradores, cláusulas de
  confidencialidade), não patente.
- **A decisão de mover reconhecimento facial de "contínuo" para "busca sob
  demanda"** é uma escolha de produto interessante e defensável
  comercialmente (menor custo de CPU, melhor privacidade — não processa
  biometria continuamente, só quando o cliente pede), mas também não é uma
  técnica nova o suficiente para proteção por patente — é uma decisão de
  produto/UX apoiada em arquitetura existente.
- **Registro de programa de computador** (não confundir com patente) — no
  Brasil, o código-fonte do Next Sec, como qualquer software original, já
  tem proteção autoral automática desde a criação (Lei 9.609/98, art. 2º).
  O registro no INPI (opcional, mas recomendável para fins probatórios de
  data de criação e titularidade) é o instrumento correto aqui — **não**
  uma patente.

### 9.3 Elegibilidade a programas de incentivo à inovação (leitura preliminar)

Diferente de patente, programas como **Lei do Bem** (Lei 11.196/05, incentivo
fiscal a P&D) e **Lei de Informática** costumam avaliar **processo de P&D com
risco tecnológico**, não "ineditismo absoluto no mundo". Sob essa ótica, há
elementos genuínos no histórico deste projeto que **poderiam** ser
documentados como atividade de P&D, se o objetivo for buscar esse tipo de
incentivo:

- Iteração real com hipóteses testadas e refutadas (ex: calibração de
  tracking a baixo FPS, decisão de mover reconhecimento facial de contínuo
  para sob demanda após constatar custo de CPU inviável na VPS-alvo);
- Comparação formal e documentada de alternativas técnicas com critérios
  objetivos (ADR-014, matriz InsightFace vs. dlib vs. DeepFace);
- Validação empírica de cada decisão (não é só escolha teórica — cada ADR
  relevante tem uma seção "Validado" com evidência real de execução).

Isso é o tipo de documentação que auditorias de Lei do Bem costumam pedir
(registro do processo de pesquisa, não só do resultado). **Mas** — sendo
honesto de novo — isso não é o mesmo que "temos uma invenção protegível".
É "temos um processo de desenvolvimento com risco tecnológico documentável",
o que é o critério real desses programas fiscais, diferente do critério de
patente. Vale conversa com um contador especializado nesse tipo de incentivo
para avaliar se o porte da empresa e o volume de P&D justificam o esforço de
compliance exigido (é um processo de auditoria não trivial).

### 9.4 Conclusão da seção

**Resumo em uma frase:** o Next Sec não tem, hoje, uma técnica isolada
patenteável — o valor real está na integração, no know-how de produto e na
execução, que se protegem por **direito autoral + segredo industrial +
velocidade de execução no mercado**, não por patente. Isso não é incomum
nem é uma fraqueza — é o padrão da maior parte dos produtos de software
B2B/B2C que vencem por execução, não por uma tecnologia isolada nunca vista
antes. Se o objetivo é atrair investimento ou defender posição de mercado, o
caminho mais realista é: registro de programa de computador no INPI +
contratos de confidencialidade + velocidade de iteração, não uma corrida por
patente que provavelmente não seria concedida.

---

## 10. Referências internas

| Documento | Conteúdo |
|---|---|
| `.genesis/manifest.md` | Requisitos originais, público-alvo, escopo |
| `.genesis/architecture/adrs/001` a `014` | Decisões arquiteturais individuais, com racional e trade-offs |
| `.genesis/architecture/adrs/015-edge-inference.md` | Decisão de mover inferência de vídeo pro edge, motivada pelo incidente de produção (seção 7.2-bis) |
| `.genesis/architecture/adrs/016-edge-two-tier-deployment.md` | Modelo de dois níveis (Docker dedicado / agent nativo embutido / VPS fallback) — estende a ADR-015 |
| `.genesis/architecture/tech-stack.md` | Stack completa com justificativa por camada |
| `.genesis/architecture/reuse-plan.md` | O que veio do `vms/`, o que é novo, bugs encontrados e corrigidos |
| `.genesis/memory/progress.md` | Histórico sprint a sprint com status real |
| `next_sec/docs/DEPLOY_VPS.md` | Processo real de deploy na VPS compartilhada, validado nesta sessão |
| `next_sec/infra/wireguard/entrypoint.sh`, `control_api.py` | Implementação real do hub WireGuard |
| `next_sec/api/src/vms/cameras/wireguard_client.py` | Lado da API que provisiona peers |
