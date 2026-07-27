# Deploy na VPS compartilhada (fastos, 2.25.180.57)

O Next Sec compartilha hardware com **FastOS** e **Civix**, já em produção
nessa VPS (2 vCPU / 8 GB RAM / 96 GB disco, Ubuntu 24.04). Portas 80/443
já são ocupadas pelo nginx do FastOS (`fastos-prod-nginx-1`) — o Next Sec
**não** publica essas portas; ele fica atrás desse nginx compartilhado,
conectado por uma rede Docker dedicada (`next_sec_edge`).

Antes de qualquer coisa: `docker ps` na VPS pra ver o estado atual do
FastOS/Civix (não assumir que a VPS está livre).

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

No `nginx.conf` do FastOS (`/opt/fastos`, fora deste repo), adicionar um
`server` para o domínio do Next Sec proxiando para o container pelo nome
de serviço do compose (`next_sec-nginx-1` ou o nome real — conferir com
`docker ps` após o primeiro `up`), via a rede `next_sec_edge`:

```nginx
server {
    listen 80;
    server_name nextsec.seudominio.com;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;   # webroot do certbot do FastOS
    }

    location / {
        proxy_pass http://next_sec-nginx-1:80;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Depois de emitir o certificado (certbot do próprio FastOS, mesmo processo
usado pra Civix), adicionar o `server` `listen 443 ssl` equivalente.
O Next Sec **não** termina TLS — quem faz isso é sempre o nginx do FastOS.

> O nginx do Next Sec já serve `/.well-known/acme-challenge/` a partir de
> `/var/www/certbot` (ver `infra/nginx/nginx.conf`) — é uma segunda opção
> caso um dia o desafio ACME precise ser repassado até aqui em vez de
> resolvido direto no nginx do FastOS. Normalmente não é necessário.

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

## 8. Observação de segurança (revisar antes de ir ao ar)

`docker-compose.yml` ainda publica no host algumas portas que só existem
para conveniência de dev local: RabbitMQ management (`15672`), console do
MinIO (`9000`/`9001`) e RTSP do MediaMTX (`8554`). O tráfego real do agent
(API + RTMP) já passa pelo túnel WireGuard via `socat` no hub
(`infra/wireguard/entrypoint.sh`), então essas portas não precisam estar
expostas publicamente em produção — vale um `docker-compose.vps.yml`
adicional zerando-as (mesmo padrão usado no nginx) antes do deploy real,
se o objetivo for produção séria e não só um piloto interno.

## Próximos passos (Sprint 5)

- [ ] S5-01 Deploy VPS compartilhada — este documento
- [ ] S5-02 Arcanum + credenciais de produção (WhatsApp)
- [ ] S5-03 Seed tenant piloto + câmera real
- [ ] S5-04 Teste E2E com câmera real
