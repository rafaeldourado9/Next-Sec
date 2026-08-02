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

## 8. Pendências de segurança (confirmadas em produção)

Este aviso existia desde o Sprint 5 como "revisar antes de ir ao ar". Em
2026-08-02 as exposições foram **verificadas de fora da VPS** e estão ativas
agora. Não é mais uma observação preventiva.

### 8.1 Painéis de administração abertos na internet

Testado de fora, contra `vm-server.duckdns.org`:

| Porta | Serviço | Resposta externa |
|---|---|---|
| `9001` | Console admin do MinIO | **HTTP 200** |
| `15672` | Management do RabbitMQ | **HTTP 200** |
| `9000` | API do MinIO | HTTP 403 (aberta, exige credencial) |
| `8554` | RTSP do MediaMTX | Aberta |

As credenciais são fortes (geradas com `openssl rand`), mas painéis de
administração não deveriam estar acessíveis publicamente — nenhum fluxo do
produto depende disso.

**Correção:** zerar a publicação dessas portas no compose (mesmo padrão
`ports: !reset []` já usado no nginx). Nada quebra: o MinIO é consumido pela
API pela rede interna do Docker, e o RabbitMQ management é ferramenta de
diagnóstico.

A porta `1935` (RTMP) deixa de ser necessária com a
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
mediamtx api worker frontend nginx`. **Não estão rodando:**

- `backup-scheduler` — **não há backup do banco**. Inaceitável antes de
  qualquer cliente real.
- `analytics` — nenhuma detecção acontece na VPS (esperado pela ADR-019, que
  move isso para o edge, mas hoje significa que não há detecção em lugar
  nenhum).
- `arcanum` — nenhuma notificação de WhatsApp sai.

## Próximos passos (Sprint 5)

- [x] S5-01 Deploy VPS compartilhada — este documento (concluído em
      2026-07-27: stack no ar, HTTPS válido em https://vm-server.duckdns.org,
      `db=ok`/`redis=ok`/`rabbitmq=ok`/`mediamtx=ok`, WireGuard 51820/udp
      escutando; `analytics=degraded` é esperado, sem câmera cadastrada ainda)
- [ ] S5-02 Arcanum + credenciais de produção (WhatsApp)
- [ ] S5-03 Seed tenant piloto + câmera real
- [ ] S5-04 Teste E2E com câmera real
