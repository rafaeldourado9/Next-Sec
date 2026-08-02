# Deploy na VPS (2.25.180.57)

> ## ⚠️ DESATUALIZADO a partir de 2026-08-02
>
> Este documento descreve o setup **antigo** (VPS compartilhada com FastOS e
> Civix, nginx do FastOS terminando TLS). Em 2026-08-02 a VPS foi encontrada
> **vazia** — zero containers, zero volumes, zero imagens Docker; 49 dias de
> uptime, então a máquina não foi reinstalada, apenas o estado do Docker
> desapareceu. **FastOS e Civix não existem mais nessa máquina.**
>
> O Next Sec foi reprovisionado do zero e agora é **dono direto das portas
> 80/443**, terminando TLS ele mesmo (ver `infra/nginx/ssl-server.conf.template`
> e `docker-entrypoint.sh`). As seções 2, 3 e 6 abaixo — rede compartilhada
> `next_sec_edge`, `docker cp` do vhost no container do FastOS e
> `docker-compose.vps.yml` — **não se aplicam mais**.
>
> Fluxo atual: `cd /opt/next_sec && git pull && docker compose build <svc> &&
> docker compose up -d <svc>`. O certificado Let's Encrypt é emitido por
> certbot webroot (ver §3) e **renovado manualmente** a cada ~80 dias.
>
> **Ver também: [§8 Pendências de segurança](#8-pendências-de-segurança-confirmadas-em-produção)
> — há exposições confirmadas em produção agora.**

O Next Sec roda numa VPS de 2 vCPU / 8 GB RAM / 96 GB disco, Ubuntu 24.04.

Antes de qualquer coisa: `docker ps` na VPS pra ver o estado atual (não
assumir que a VPS está livre nem que está como este documento descreve).

## 1. Variáveis de ambiente de produção

Copiar `.env.example` → `.env` no servidor e **trocar todos os valores
`*-change-in-production`**:

| Variável | Como gerar/definir |
|---|---|
| `SECRET_KEY` | `openssl rand -hex 32` |
| `VMS_API_KEY` | `openssl rand -hex 32` |
| `WG_CONTROL_TOKEN` | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` / `RABBITMQ_PASSWORD` | senha forte, atualizar também `DATABASE_URL`/`RABBITMQ_URL` |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | senha forte |
| `DOMAIN` | domínio real do Next Sec (ex: `nextsec.seudominio.com`) |
| `WG_PUBLIC_ENDPOINT` | `<ip-da-vps>:51820` — é o que o agent Windows disca |
| `RTMP_PUBLIC_URL` | `rtmp://<ip-da-vps>:1935` (informativo, exibido no wizard) |
| `ENVIRONMENT` | `production` |

`.env` nunca vai pro git — criar direto no servidor.

## 2. Rede compartilhada `next_sec_edge`

Criada fora do compose (não é gerenciada por nenhum dos dois projetos):

```bash
docker network create next_sec_edge
```

Conectar o nginx do FastOS a ela (sem tirar da rede que ele já tem):

```bash
docker network connect next_sec_edge fastos-prod-nginx-1
```

O `docker-compose.vps.yml` já coloca o nginx do Next Sec nessa mesma rede
e zera a publicação de porta (`ports: !reset []`) — ver comentário no
próprio arquivo.

## 3. Server block no nginx do FastOS

O vhost já está pronto em `deploy/next-sec-prod-vhost.conf` (domínio real:
`vm-server.duckdns.org`, DuckDNS). Instalar no container do nginx do
FastOS (não é um bind mount, é `docker cp` direto — as mudanças somem se
o container for recriado, daí o `deploy/next-sec-route-reconcile.sh`):

```bash
docker network connect next_sec_edge fastos-prod-nginx-1
docker cp deploy/next-sec-prod-vhost.conf fastos-prod-nginx-1:/etc/nginx/conf.d/next-sec.conf
docker exec fastos-prod-nginx-1 nginx -t && docker exec fastos-prod-nginx-1 nginx -s reload
```

Depois de emitir o certificado, adicionar o `server` `listen 443 ssl`
equivalente. O Next Sec **não** termina TLS — quem faz isso é sempre o
nginx do FastOS.

> **Importante:** o `renew-ssl.sh`/`init-ssl.sh` do FastOS usam
> `certbot/dns-cloudflare` (desafio DNS-01 via API da Cloudflare) — isso
> só funciona para domínios cujo DNS é gerenciado pela Cloudflare.
> `vm-server.duckdns.org` é DuckDNS, não Cloudflare, então **não dá** pra
> usar esse script. Use desafio HTTP-01 via webroot, apontando pro mesmo
> `/var/www/certbot` que o nginx do Next Sec já serve (ver
> `infra/nginx/nginx.conf`), que é bind-mounted em `infra/nginx/certbot/`
> no host:
>
> ```bash
> docker run --rm \
>   -v fastos_letsencrypt_certs:/etc/letsencrypt \
>   -v /opt/next_sec/infra/nginx/certbot:/var/www/certbot \
>   certbot/certbot certonly --webroot -w /var/www/certbot \
>   -d vm-server.duckdns.org --email equipe@fastosystems.com.br \
>   --agree-tos --non-interactive
> ```
>
> Isso exige que o vhost `:80` já esteja no ar (proxy pro Next Sec) *antes*
> de emitir o certificado, servindo `/.well-known/acme-challenge/` — ver
> `deploy/next-sec-prod-vhost.conf` (primeiro server block).
>
> **Renovação:** este certificado não está coberto pelo cron do
> `renew-ssl.sh` (que só renova domínios Cloudflare). Renovar manualmente
> a cada ~80 dias repetindo o comando acima, ou automatizar depois com um
> cron/systemd timer dedicado.

## 4. Firewall

Abrir **UDP 51820** (WireGuard) no firewall da VPS/provedor — é a porta
pública que o agent Windows disca para atravessar CGNAT. Portas HTTP/HTTPS
já são cobertas pelo nginx do FastOS.

## 5. Instalador Windows do agent

`native_installer/windows/release/` já contém o `.exe` (PyInstaller) e os
scripts `.ps1`/`.bat` — esse diretório é montado como volume read-only no
nginx do Next Sec (`/downloads/agent-windows/`). Se o binário for
reconstruído, gerar de novo antes do `up` (`docker compose build nginx`
sozinho não resolve — o conteúdo vem do host, não da imagem).

## 6. Subir a stack

```bash
cd /opt/next_sec   # ou onde o repo for clonado na VPS
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d --build
```

- `ANALYTICS_TARGET` fica em `cpu` (default) — sem GPU nessa VPS.
- Migrations rodam sozinhas no start do `api` (`alembic upgrade head` no
  `CMD` do estágio `production`, ver `api/Dockerfile`).
- `docker compose ps` deve mostrar todos os serviços `healthy`.

## 7. Smoke test

```bash
curl http://localhost/api/v1/health          # dentro da VPS, via porta interna do container
curl https://nextsec.seudominio.com/api/v1/health   # de fora, via nginx do FastOS
```

Confirmar `db=ok`, `redis=ok`, `rabbitmq=ok` na resposta.

## 8. Pendências de segurança

### 8.1 Painéis de administração abertos na internet — ✅ CORRIGIDO (2026-08-02)

Este aviso existia desde o Sprint 5 como "revisar antes de ir ao ar". Em
2026-08-02 as exposições foram **verificadas de fora da VPS** e estavam
ativas:

| Porta | Serviço | Antes | Depois |
|---|---|---|---|
| `9001` | Console admin do MinIO | **HTTP 200 público** | fechada |
| `15672` | Management do RabbitMQ | **HTTP 200 público** | fechada |
| `9000` | API do MinIO | aberta (403) | fechada |
| `8554` | RTSP do MediaMTX | aberta | fechada |

**Correção aplicada:** amarradas a `127.0.0.1` no `docker-compose.yml`, em
vez de removidas. Continuam funcionando em dev (é assim que se acessa de
qualquer jeito) e, na VPS, ficam acessíveis por túnel SSH:

```bash
ssh -L 15672:127.0.0.1:15672 -L 9001:127.0.0.1:9001 root@2.25.180.57
```

Nada do produto consome essas portas pelo host — a API fala com o MinIO pela
rede interna do Docker (`MINIO_ENDPOINT=http://minio:9000`).

Portas públicas restantes: `80`/`443` (nginx), `1935` (RTMP) e `51820`
(WireGuard). A `1935` deixa de ser necessária com a
[ADR-019](../../.genesis/architecture/adrs/019-edge-first-vps-events-only.md)
— o vídeo passa a não atravessar mais a VPS.

### 8.2 MediaMTX central com autenticação de publicação inexistente

`infra/mediamtx/mediamtx.yml` define `authMethod: http` apontando para
`<base>/streaming/publish-auth`. **Esse endpoint não existe na API** — não há
nenhuma rota com o prefixo `/streaming`. Toda publicação RTMP é recusada com
`failed to authenticate: server replied with code 404` (confirmado nos logs
de produção).

O comportamento é fail-closed, então **não é uma brecha** — é uma
funcionalidade que nunca funcionou. A ADR-019 resolve por remoção: o caminho
de vídeo até a VPS deixa de existir.

> **Consequência ainda não tratada:** o mesmo `authHTTPAddress` valida também
> a **leitura** (HLS/WebRTC). Ou seja, assistir vídeo através da VPS também
> está quebrado hoje — o que é coerente com a ADR-019 (visualização passa a
> ser local), mas significa que **o setup Nível 3** (VPS ingere direto de uma
> câmera com IP público e serve o vídeo) **não funciona**. Se Nível 3 for um
> cenário a suportar, o endpoint precisa ser implementado. Não foi feito
> porque a ADR-019 torna esse caminho secundário.
>
> O `mediamtx.yml` é **compartilhado** entre VPS e edge, então o edge herda o
> mesmo `authHTTPAddress` apontando para a VPS. Isso merece revisão quando a
> visualização local for implementada: fazer a ingestão de vídeo **local**
> depender de um endpoint **remoto** contradiz "funciona offline" — se a
> internet cair, o cliente não conseguiria nem assistir às próprias câmeras.

### 8.5 Camera de agent provisionada no MediaMTX central — ✅ CORRIGIDO (2026-08-02)

Câmera `rtsp_pull` vinculada a um agent recebia um path no MediaMTX
**central** com `source` apontando para o RTSP dela — tipicamente um IP de
LAN inalcançável da VPS. Efeito: `dial tcp 192.168.0.101:554: i/o timeout`
em loop indefinido, e duas conexões RTSP disputando a mesma câmera.

Corrigido em `Camera.is_edge_managed`, aplicado nos quatro pontos que
provisionavam (`create_camera`, `update_camera`, o watchdog de `tasks.py` que
recriava o path a cada 30 s, e o loop de boot da API).

**Atenção ao aplicar:** `api` e `worker` são **imagens separadas**. Rebuildar
só a `api` deixa o watchdog antigo rodando no worker, que continua recriando
o path a cada ciclo:

```bash
docker compose build api worker && docker compose up -d api worker
```

Paths legados (de câmeras criadas antes da correção) não somem sozinhos —
precisam ser removidos uma vez:

```bash
docker compose exec -T api python -c "
import asyncio, httpx
async def m():
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.delete('http://mediamtx:9997/v3/config/paths/delete/<path>')
        print(r.status_code)
asyncio.run(m())"
```

### 8.3 Chave de API compartilhada resolve tenant arbitrário

`api/src/vms/plugins/router.py::_resolve_plugin_tenant` aceita uma API key
vinda de variável de ambiente (`VMS_API_KEY`) e, para ela, resolve o tenant
como *"o primeiro admin do banco"*:

```sql
SELECT tenant_id FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1
```

Numa VPS **multi-tenant**, isso associa eventos a um cliente arbitrário — o
mais antigo. É um risco de isolamento entre tenants, não apenas uma
inelegância. O caminho correto (API key por agente, emitida na ativação) já
existe desde a ADR-018; este atalho é herança do modelo single-tenant.

### 8.4 Serviços de produção não iniciados

O deploy de 2026-08-02 subiu um subconjunto: `postgres redis rabbitmq minio
mediamtx api worker frontend nginx`.

- `backup-scheduler` — ✅ **iniciado em 2026-08-02.** Ver §9.
- `analytics` — **não roda.** Nenhuma detecção acontece na VPS. É o esperado
  pela ADR-019 (que move a detecção para o edge), mas hoje significa que não
  há detecção em lugar nenhum: o agente nativo ainda só faz relay.
- `arcanum` — **não roda.** Nenhuma notificação de WhatsApp sai.

## 9. Backup do banco

`backup-scheduler` roda um `pg_dump` a cada 24 h em `/backups` (volume
nomeado `backups`), com retenção de `BACKUP_RETENTION_DAYS` (default 7).

**O dump é verificado antes de ser considerado um backup.** A versão original
fazia `pg_dump | gzip > arquivo` e seguia em frente — num pipe, o exit status
é o do último comando (`gzip`), não o do `pg_dump`. Um dump que falhasse
produzia um `.gz` válido com conteúdo truncado, e o `find -delete` logo
abaixo rotacionava os backups **bons** para fora, mantendo só os quebrados.
Verificado num container real: com o banco inacessível, o pipe retorna exit 0
e cria um arquivo de 20 bytes.

Hoje o script confere o rodapé que o `pg_dump` só escreve se chegou ao fim.
Em caso de falha, remove o arquivo ruim e **preserva** os anteriores.

### Restaurar

```bash
# Listar backups disponíveis
docker compose exec backup-scheduler ls -lh /backups/

# Restaurar num banco descartável primeiro (sempre — nunca direto em produção)
docker compose exec -T postgres psql -U vms -d postgres -c "CREATE DATABASE restore_test;"
docker compose exec -T backup-scheduler sh -c "gunzip -c /backups/<arquivo>.sql.gz" \
  | docker compose exec -T postgres psql -U vms -d restore_test
```

Restauração validada em 2026-08-02: 24 tabelas, `alembic_version = 0015`,
dados de licença preservados. **Um backup que nunca foi restaurado não é um
backup** — vale repetir esse teste periodicamente.

## Próximos passos (Sprint 5)

- [x] S5-01 Deploy VPS compartilhada — este documento (concluído em
      2026-07-27: stack no ar, HTTPS válido em https://vm-server.duckdns.org,
      `db=ok`/`redis=ok`/`rabbitmq=ok`/`mediamtx=ok`, WireGuard 51820/udp
      escutando; `analytics=degraded` é esperado, sem câmera cadastrada ainda)
- [ ] S5-02 Arcanum + credenciais de produção (WhatsApp)
- [ ] S5-03 Seed tenant piloto + câmera real
- [ ] S5-04 Teste E2E com câmera real
