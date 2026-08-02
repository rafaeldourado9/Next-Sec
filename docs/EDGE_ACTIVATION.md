# Ativação de edge por licença (ADR-018)

Ver [ADR-018](../../.genesis/architecture/adrs/018-edge-license-activation.md).

Substitui o onboarding do Sprint 7, em que cada cliente recebia um `.zip`
diferente com API key e chave privada WireGuard dentro. O objetivo é que o
cliente **instale e digite a licença** — nada mais.

> **Estado atual:** VPS, agente e instalador implementados e testados. O
> caminho do Sprint 7 (`POST /admin/onboard-client` + `.zip` com WireGuard)
> continua funcionando em paralelo, para não quebrar as instalações
> existentes. O que ainda falta está em "Ainda não feito", no fim.

## Fluxo pretendido

```
Comercial                    Cliente                         VPS
    │                           │                             │
    ├─ POST /admin/licenses ────┼────────────────────────────►│  emite a chave
    │  { tenant_id }            │                             │
    │◄──── "ABCD-12345-…" ──────┤                             │
    │                           │                             │
    ├─ entrega a chave ────────►│                             │
    │                           ├─ instala (mesmo .exe        │
    │                           │  pra todo mundo)            │
    │                           ├─ digita a licença           │
    │                           ├─ POST /edge/activate ──────►│  valida + vincula
    │                           │                             │  à máquina
    │                           │◄── api_key + policy ────────┤
    │                           ├─ grava agent.json           │
    │                           └─ começa a operar            │
```

## Endpoints

### `POST /api/v1/edge/activate` — público

Único endpoint anônimo do fluxo. Limitado a 10 req/min por IP.

```json
{ "license_key": "ABCD-12345-67890-ABCDE-FGHIJ",
  "hardware_fingerprint": "<sha256 estável da máquina>",
  "hostname": "PDV-LOJA-03",
  "agent_version": "1.0.0" }
```

Resposta (única vez que a API key trafega):

```json
{ "agent_id": "…", "api_key": "vms_…", "tenant_id": "…",
  "tenant_name": "Loja X", "api_base_url": "https://…",
  "policy": { "events_per_minute": 120, "batch_max_events": 100,
              "clip_seconds": 15, "clip_max_height": 480,
              "clip_retention_days": 30, "storage_quota_mb": 5120 } }
```

| Situação | Resposta |
|---|---|
| Licença válida, máquina nova | `200` — cria agent, vincula fingerprint |
| Mesma máquina, de novo | `200` — mesmo `agent_id`, API key **nova**, antiga revogada |
| Máquina diferente | `409` — exige desvínculo por um admin |
| Suspensa / expirada / sem cliente | `400` |
| Inexistente | `404` |
| Cliente suspenso | `400` |

Reativar na mesma máquina precisa ser idempotente porque reinstalação de
Windows, restauração de backup e perda do `agent.json` são rotina — se cada
uma virasse um chamado de suporte, o mecanismo pioraria o que veio resolver. O
agent é reaproveitado (as câmeras estão ligadas ao `agent_id`); só a
credencial é trocada.

### `POST /api/v1/edge/events:batch` — API key do agente

Até 100 eventos por request, **sem mídia**. Cada item leva um
`client_event_id` (UUID do edge) que serve de chave de idempotência: reenvio
depois de um timeout devolve `duplicate` com o `event_id` original, em vez de
duplicar.

A resposta traz o veredito de cada item (`accepted` / `duplicate` /
`rejected`) — o agente só limpa da fila local o que a VPS confirmou.

**Cota por tenant** (token bucket no Redis, custo = tamanho do lote):

- Dentro da cota → `200` + `X-RateLimit-Remaining`
- Acima → `429` + `Retry-After`, **nada gravado**, lote inteiro volta pro
  outbox do agente

A cota falha aberta: se o Redis cair, a requisição passa. Cota é proteção
contra abuso, não controle de integridade — recusar a ingestão de todos os
clientes porque o Redis piscou trocaria um problema hipotético por perda real
de evento.

### `POST /api/v1/edge/heartbeat` — API key do agente

Mantém `last_seen_at` e devolve a policy vigente, para mudar a cota ou a
duração do clipe de um cliente pelo painel e ver o efeito na instalação dele
em um minuto, sem ninguém tocar na máquina.

O corpo leva `outbox_pending` e `outbox_dropped` — o sintoma mais útil que a
VPS tem de um edge com problema, já que ela não consegue olhar lá dentro.

### `PUT /api/v1/edge/events/{id}/snapshot` e `.../clip`

Terceiro passo: a mídia sobe **só para os eventos que a VPS aceitou**, em
requisições próprias. Separar isso do `:batch` é o que impede um lote de 100
eventos de ficar refém do upload de um JPEG.

É o endpoint de **snapshot**, não o `:batch`, que enfileira a notificação: o
alerta de WhatsApp manda a imagem junto, então notificar antes dela chegar
produziria uma mensagem sem a evidência.

O **clipe** é recusado com `413` quando o cliente estourou `storage_quota_mb`
— mas o evento e a foto permanecem. É deliberado: o cliente continua enxergando
o que aconteceu e recebendo alerta; perde a evidência em vídeo, que é o item
caro, não o registro.

### Admin

| Endpoint | Para quê |
|---|---|
| `POST /admin/licenses` | Emite uma licença para um tenant. Devolve **só a string** |
| `GET /admin/licenses` | Quem ativou, em que máquina, última batida |
| `POST /admin/licenses/{id}/unbind` | Cliente trocou de hardware. Revoga a credencial da instalação antiga junto |

## Backpressure no edge

O `EventOutbox` (`analytics/core/outbox.py`) fecha o outro lado do laço:

- `429` é tratado como **retentável** (ao contrário dos demais 4xx) e adia a
  **fila inteira** por `Retry-After` — adiar só o item recusado faria o
  próximo bater na mesma parede um instante depois.
- `Retry-After` tem teto de 15 min: um valor disparatado (bug da VPS, proxy
  hostil no meio) congelaria a fila do cliente sem ninguém perceber.
- Cap de 50 000 itens / 7 dias, descartando os mais antigos. O item novo é
  sempre aceito: com a fila cheia, o cliente precisa preservar o que está
  acontecendo agora, não o que aconteceu há dias.

## Instalação na máquina do cliente

Um executável só, igual para todos. Nada de WireGuard, nada de `config.env`.

```
INSTALAR-LICENCA.bat          → auto-eleva e chama install-licensed.ps1
  → pergunta endereço do servidor e chave de licença
  → next-sec-agent.exe activate <chave> --api-url <url>
  → grava %ProgramData%\NextSecAgent\agent.json (ACL: SYSTEM + Administradores)
  → só então registra o serviço NextSecAgent (NSSM, auto-start, auto-restart)
```

A ativação acontece **antes** de registrar o serviço, e o instalador aborta
mostrando o erro. Ativar depois esconderia "licença já usada em outra máquina"
num log de serviço que ninguém vai abrir — o cliente veria uma instalação
"concluída" que simplesmente não funciona.

Comandos úteis para o suporte:

| Comando | Para quê |
|---|---|
| `next-sec-agent.exe status` | Estado da ativação. **Não** imprime a API key — é o comando que o cliente cola num chat |
| `next-sec-agent.exe fingerprint` | ID desta máquina, para pedir desvínculo |
| `next-sec-agent.exe activate <chave> --api-url <url> --force` | Reativa (reemite a credencial, revogando a anterior) |

### Fingerprint da máquina

Deriva do UUID de sistema (`MachineGuid` no Windows, `/etc/machine-id` no
Linux), com o UUID do chassi (SMBIOS) como reforço. **Não** entram na conta:
MAC de rede (muda com adaptador USB/VPN), série de disco (troca de HD é
manutenção rotineira) nem nada que o cliente troque sem trocar de máquina. Ou
seja: erra para o lado de "continua valendo" em vez de "invalidou sozinho" —
o vínculo existe para dificultar cópia, não para ser um dongle.

### Credencial revogada

Suspender a licença, desativar o cliente ou desvincular a máquina revoga a API
key. O agente toma `401` na próxima chamada e **encerra**, registrando o
motivo, em vez de reconectar em silêncio para sempre.

## O clipe de 15 s: agora com movimento

Até aqui o "clipe" era o JPEG do evento esticado em vídeo
(`render_freeze_frame_clip`) — não havia alternativa, porque nada guardava
vídeo contínuo acessível na hora de montá-lo. Com a gravação contínua morando
na máquina do cliente, o edge passa a recortar vídeo de verdade da própria
gravação:

1. Localiza o segmento do MediaMTX que contém o instante do evento
   (`recordPath: /recordings/%path/%Y-%m-%d_%H-%M-%S-%f`).
2. Espera a janela do clipe ser escrita em disco — o segmento fmp4 é gravado em
   partes de 1 s, então o trecho *posterior* ao evento ainda não existe no
   instante em que ele é confirmado.
3. Corta `clip_seconds` a partir de 5 s **antes** do evento (um alerta de
   intrusão que começa com a pessoa já dentro da cena é bem menos útil que um
   que mostra a aproximação) e reencoda para `clip_max_height`.
4. Cai no freeze-frame quando não há gravação cobrindo aquele instante —
   câmera com gravação desligada, ou evento fora da retenção local.

O reencode roda no hardware do cliente. A VPS nunca toca em ffmpeg para
eventos de edge.

## Limites e o orçamento da VPS

O que decide se uma VPS pequena aguenta não é a contagem de eventos — é a
mídia. Com o teto de clipe da ADR-018 §4 (15 s a 480 p ≈ 500 KB):

| Cenário | Clipe/dia | Estável a 30 dias |
|---|---|---|
| 1 000 tenants × 10 eventos/dia | ~5 GB | ~150 GB |
| o mesmo, sem teto de resolução (720 p) | ~37 GB | ~1,1 TB |

A gravação contínua **nunca sai da máquina do cliente**.

## Ainda não feito

1. **`analytics` ainda envia evento a evento** por `POST /plugins/events`
   (multipart com o JPEG inline). O `:batch` existe e está testado, mas quem
   produz evento hoje é o `analytics`, e migrá-lo significa reescrever
   `VMSClient.ingest_event` para acumular lote + subir mídia em seguida. Até
   lá, a cota por tenant só protege quem já usa o caminho novo.
2. **Parar de chamar a VPS a cada segmento** de gravação contínua
   (`runOnRecordSegmentComplete` no `mediamtx.yml`) — hoje ainda há um POST por
   segmento, que é custo puro na VPS para um índice que o edge poderia servir.
3. **Empacotar mediamtx + runtime de inferência no agente nativo.** O
   `install-licensed.ps1` já instala o agent como serviço sem Docker, mas o
   agent nativo ainda não roda análise nem ingestão de vídeo — isso continua no
   `docker-compose.edge.yml`. É o item mais caro do plano (bundle na casa de
   GB) e o que finalmente elimina o Docker Desktop e o login automático do
   Windows com senha em texto plano.
4. **Frontend** — emissão de licença e desvínculo no painel admin; remoção da
   geração do `.zip` em `TenantsPage.tsx`.
