# Gravação contínua local + timeline de playback

> **Status desta sessão (2026-07-27):** implementação quase completa.
> Concluído: migration 0009, config opt-in do MediaMTX (com fix real de
> `delete+add` no lugar de `edit`, que retorna 404 de rota nesta versão do
> MediaMTX pra paths com `/` no nome), bounded context `recordings/`
> completo, frontend (`RecordingTimeline`, `RecordingPlayer`, modo VOD do
> `VideoPlayer`, aba nova em `CameraDetailPage`), gravação testada e
> validada com `ffprobe` (H264 válido). **Pendente/em depuração:** o
> `auth_request` do nginx pro `/mediamtx-playback/` está bloqueando mesmo
> com token válido (401) — confirmado que o endpoint `/internal/verify-
> playback-token` funciona certo quando chamado direto, então o problema é
> como a subrequest do `auth_request` propaga (ou não) o query string
> original pro nginx. Precisa investigar com `log_subrequest on` antes de
> fechar a task #7. Também pendente: canário de crash formal (task #8) e
> teste ponta a ponta final (task #11).

## Contexto

Hoje o Next Sec só grava um "clipe" de evento (imagem única esticada em N segundos via ffmpeg — `event_clips/`) porque gravação contínua foi explicitamente desligada no MVP (`mediamtx.yml`: `pathDefaults.record: no`). O usuário quer o padrão moderno de timeline fluida (fMP4 contínuo + manifest HLS gerado dinamicamente por byte-range, sem quebrar ao cruzar segmentos) — e o MediaMTX que já roda no stack faz exatamente isso nativamente: seu servidor de VOD (`playback: yes`, porta 9996, já proxied em `/mediamtx-playback/` no nginx) monta o manifest on-the-fly a partir dos fMP4 gravados, para qualquer intervalo `start`/`end`. Isso já está todo plugado, só falta ter arquivo gravado pra servir.

Existe um incidente documentado (comentário em `api/src/vms/cameras/mediamtx.py`): uma tentativa anterior de `record: True` por câmera derrubou o muxer HLS ao vivo junto, porque o recorder travava em frames fora de ordem (câmera WiFi/RTSP instável, UDP perdendo/reordenando pacote). A correção aplicada foi reverter a gravação e forçar `sourceProtocol: tcp` — o que reduz bastante o gatilho, mas não elimina o risco por completo. Este plano trata isso como risco residual real, não teórico, com rollout em canário.

Decisões já confirmadas com o usuário:
- **Nuvem fica de fora desta rodada** — só grava local. O `StorageProvider` (interface já existente em `api/src/vms/infrastructure/storage_provider.py`) fica pronto pra receber um segundo provider depois, sem mexer agora.
- **Retenção por dias, usando `CameraModel.retention_days`** (já existe, default 7 dias) — mapeado direto pro `recordDeleteAfter` nativo do MediaMTX, que é quem de fato apaga os arquivos.
- **Índice no banco é só "janelas contíguas"** (não 1 linha por segmento de 15min) — o worker nunca mexe em vídeo, só mantém um índice leve de "quais intervalos de tempo têm gravação" pra sombrear a timeline no frontend. Quem apaga o arquivo é o MediaMTX (`recordDeleteAfter`), não o worker.
- **Fechar o buraco de autenticação do playback nesta rodada** — hoje `/mediamtx-playback/` não tem nenhuma auth (qualquer um com o UUID da câmera puxa vídeo gravado sem token). Isso é inaceitável já que o nginx está exposto via túnel Cloudflare. Vai ganhar um `auth_request` no nginx + token assinado com o intervalo embutido, no mesmo padrão do `/stream-urls` existente.

## Achados durante a implementação (não previstos no plano original)

1. **`config/paths/edit/{name}` retorna 404 de rota** (não erro de app) pra
   nomes de path com `/` nesta versão do MediaMTX — confirmado via teste
   direto. O fix real é `delete` + `add` pra reconfigurar um path existente
   (breve reconexão do stream, aceitável numa mudança deliberada). Código
   antigo tratava o 400 subsequente do `add` como "já existe, sucesso" —
   mascarando que a config nunca era de fato atualizada.
2. **`add_path` precisou de um parâmetro `force`** — o early-return original
   (path já ativo → no-op) preservado pro caso comum (evita reprovisionar
   toda câmera a cada boot/watchdog), mas o loop de startup do `main.py`
   precisa de `force=True` sempre (reconcilia o MediaMTX com o banco mesmo
   quando o RTSP real já reconectou rápido e o path já aparece "ready"
   antes do loop rodar).
3. **Watchdog (`cameras/tasks.py`) e startup (`main.py`) precisam passar
   `recording_enabled`/`retention_days`** no re-provisionamento — sem isso,
   um restart do MediaMTX + auto-cura do watchdog desligaria a gravação em
   silêncio (voltando pro default `record: False`).
4. **Capacidade de disco real**: câmera de teste em "source quality"
   (2688x1520) gravou ~85MB em 2,6min ≈ 47GB/dia. Com retenção de 5 dias
   isso passaria de 200GB — acima dos 96GB totais do disco (ADR-005).
   Decisão pendente do usuário: sub-stream de qualidade menor pra gravação
   contínua, ou retenção bem mais curta.
5. **`auth_request` bloqueando com token válido (401)** — em depuração no
   momento em que este documento foi salvo. `verify-playback-token`
   funciona quando chamado direto; suspeita é como `$is_args$args` se
   comporta dentro da subrequest do `auth_request`. `log_subrequest on`
   adicionado na location interna pra depurar (ainda não validado).

## Abordagem recomendada

### 1. MediaMTX — gravação opt-in por câmera, não global

`pathDefaults.record` continua `no` (é literalmente o que causou o incidente anterior quando era implícito/global). Gravação liga por path, via API, só para câmeras com o novo campo `recording_enabled=True`.

**`infra/mediamtx/mediamtx.yml`** — adiciona defaults herdados quando um path liga gravação (inofensivo enquanto `record: no` global):
```yaml
pathDefaults:
  record: no
  recordPath: /recordings/%path/%Y-%m-%d_%H-%M-%S-%f
  recordFormat: fmp4
  recordSegmentDuration: 15m       # limita o "raio de explosão" de um segmento corrompido
  recordDeleteAfter: 0s            # override por path = retention_days da câmera
  runOnRecordSegmentComplete: >-
    wget -qO- --header="Content-Type: application/json"
    --post-data="{\"path\":\"$MTX_PATH\",\"segment_path\":\"$MTX_SEGMENT_PATH\"}"
    http://api:8000/api/v1/webhooks/mediamtx/on_record_segment_complete
```

**`api/src/vms/cameras/mediamtx.py`** — `MediaMTXClient.add_path` ganha `recording_enabled: bool`, `retention_days: int | None` e `force: bool`. Reconfiguração de path existente usa `delete`+`add` (não `edit` — ver achado #1 acima).

**Risco de crash — mitigação:**
- `recording_enabled` default `False` no banco (opt-in, não automático pra câmeras existentes).
- Rollout em canário: ligar em **uma única câmera não-crítica primeiro**, observar logs do MediaMTX (`too many reordered frames`, panics) e — crítico — se `is_online` de **outras** câmeras oscilar durante o teste, isso é sinal de que o crash é do processo inteiro, não só do path. Só depois de uma janela limpa libera o toggle pras outras câmeras. **(Task #8 — ainda pendente formalmente, mas já observamos `[recorder] detected drift between recording duration and absolute time, resetting` + perda de pacote RTP real sem derrubar o processo, o que é um bom sinal.)**

### 2. docker-compose.yml

Volume nomeado `recordings`, montado só no `mediamtx` (rw). `api`/`nginx`/`worker` não montam — falam com o MediaMTX só via HTTP.

### 3. Migration `0009` — aplicada

`cameras.recording_enabled` (bool, default false) + tabela `recording_windows` (índice de cobertura, 1 linha por sessão contígua).

### 4. Backend — implementado

- `cameras/`: `recording_enabled` em domain/schemas/repository/service/router.
- `api/src/vms/recordings/`: `models.py`, `domain.py`, `repository.py`, `service.py`, `tasks.py`, `router.py` — espelha `event_clips/`.
- Rotas `GET /cameras/{id}/recordings/availability` e `/playback-url` — testadas via curl, funcionando.
- Webhook `POST /webhooks/mediamtx/on_record_segment_complete` — testado, indexando janelas.
- `create_playback_token` em `infrastructure/security.py` — token JWT com tenant/câmera/intervalo embutido, 60min de validade.

### 5. Worker — implementado

`task_prune_recording_windows` registrada em `WorkerSettings.functions`/`cron_jobs` (03:45, depois do cleanup de clipes).

### 6. Nginx — implementado, EM DEPURAÇÃO

```nginx
location /mediamtx-playback/ {
    auth_request /internal/verify-playback-token;
    proxy_pass         http://mediamtx_playback/;
    ...
}

location = /internal/verify-playback-token {
    internal;
    log_subrequest on;  # debug temporário — remover depois de resolver
    proxy_pass              http://vms_api/api/v1/internal/verify-playback-token$is_args$args;
    proxy_set_header        Host $host;
    proxy_pass_request_body off;
    proxy_set_header        Content-Length "";
}
```

Bloqueia corretamente sem token (401 confirmado). **Com token válido também retorna 401** — bug ainda não resolvido nesta sessão. Próximo passo: confirmar com `log_subrequest on` se `$args` chega correto na subrequest, ou se é preciso usar `auth_request_set` pra propagar explicitamente.

### 7. Frontend — implementado

- `RecordingTimeline.tsx`, `RecordingPlayer.tsx`, modo `vod` no `VideoPlayer.tsx`, aba "Gravações" em `CameraDetailPage.tsx` (com toggle de `recording_enabled` no formulário de edição), métodos novos em `services/cameras.ts`. Typecheck limpo.

## Ordem de implementação (atualizada)

1. ~~Migration `0009`~~ ✅
2. ~~`mediamtx.yml` + volume~~ ✅
3. ~~`MediaMTXClient.add_path` (recording params + fix delete/add + force)~~ ✅
4. ~~Verificar gravação (`ffprobe`)~~ ✅ — H264 válido, 2688x1520, sem corrupção
5. **Verificar playback via curl + auth_request — EM ANDAMENTO, bug de 401 com token válido**
6. Canário de crash formal — pendente
7. ~~Bounded context `recordings/`~~ ✅
8. Verificar `task_prune_recording_windows` manualmente — pendente
9. ~~Frontend~~ ✅ (código pronto, falta build/deploy + teste real no browser)
10. Teste manual ponta a ponta com câmera real — pendente (bloqueado pelo bug do auth_request)

## Decisão pendente do usuário

**Capacidade de disco**: câmera em qualidade "source" grava ~47GB/dia. Precisa decidir entre:
- (a) usar sub-stream de qualidade menor pra gravação contínua (câmera precisa suportar múltiplos streams);
- (b) retenção bem mais curta que 5 dias pra essa câmera;
- (c) aceitar o custo de disco e expandir a VPS.

## Arquivos principais
- `infra/mediamtx/mediamtx.yml`
- `api/src/vms/cameras/mediamtx.py`, `service.py`, `schemas.py`, `domain.py`, `repository.py`, `router.py`, `tasks.py`
- `api/src/vms/recordings/` (novo)
- `api/migrations/versions/0009_add_recording.py`
- `api/src/vms/worker.py`, `main.py`
- `infra/nginx/nginx.conf`
- `docker-compose.yml`
- `frontend/src/components/camera/VideoPlayer.tsx`, `RecordingTimeline.tsx`, `RecordingPlayer.tsx`
- `frontend/src/pages/CameraDetailPage.tsx`
- `frontend/src/services/cameras.ts`
