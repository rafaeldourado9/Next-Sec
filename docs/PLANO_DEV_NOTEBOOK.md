# Plano de desenvolvimento em duas máquinas

Divisão do trabalho entre o desktop atual e o notebook, com o setup do
notebook do zero.

## As duas máquinas

| | Desktop (`DESKTOP-919CF02`) | Notebook (Inspiron 15) |
|---|---|---|
| RAM | ~16 GB | 16 GB |
| CPU | — | Intel, sem GPU dedicada |
| Chave SSH da VPS | **sim** (`~/.ssh/id_ed25519_vps`) | não |
| Agente instalado como serviço | **sim** (`NextSecAgent`) | não |
| Câmera Hikvision na LAN | **sim** (`192.168.0.101`) | depende de estar na mesma rede |
| Venv do PyInstaller | **sim** (`edge_agent/.venv-native`) | não |
| Imagens Docker do projeto | **sim**, já construídas | não |

A divisão abaixo não é arbitrária — segue dessas diferenças.

## Quem faz o quê, e por quê

### Notebook → performance do edge

O Inspiron 15 com Intel e sem GPU **é a classe de hardware alvo** da
[ADR-019](../../.genesis/architecture/adrs/019-edge-first-vps-events-only.md)
§3. Medir performance nele é medir no cliente, não numa aproximação. CPU
Intel também dá acesso a OpenVINO e QuickSync, que são exatamente as
alavancas do plano.

Agenda, na ordem de [`EDGE_PERFORMANCE.md`](EDGE_PERFORMANCE.md):

1. **Benchmark de inferência** — PyTorch FP32 640 vs ONNX FP32 640 vs ONNX
   INT8 320. É o número que define se o alvo é 16 câmeras ou menos; **tudo
   o mais depende dele**.
2. **Migração para ONNX Runtime INT8** — maior ganho isolado, e tira o torch
   (~1 GB) da memória residente.
3. **Gating de movimento antes da inferência** — hoje o `DetectionCache`
   decide *depois* do YOLO, quando o custo dominante já foi pago.
4. **Perfil de hardware fraco** — forçar `frame_enhance` e reconhecimento
   facial desligados.

Arquivos que essa frente toca: `analytics/**` (principalmente
`core/shared_inference.py`, `core/yolo_base.py`, `core/detection_cache.py`,
`core/config.py`).

**Não precisa de câmera real.** Existe `analytics/core/file_frame_source.py`
— o benchmark deve rodar sobre um arquivo de vídeo fixo, que é mais
reprodutível que uma câmera ao vivo (mesmo conjunto de frames em toda
execução, comparação justa entre backends).

### Desktop → VPS, agente e instalador

Fica aqui o que depende de coisa que só existe aqui:

1. **Fechar as portas expostas** (`9001`, `15672`, `9000`, `8554`) — precisa
   da chave SSH da VPS. Ver [`DEPLOY_VPS.md`](DEPLOY_VPS.md) §8.1. **É o item
   mais urgente do projeto todo.**
2. **Subir o `backup-scheduler`** — não há backup do banco hoje (§8.4).
3. **Remover o caminho de vídeo até a VPS** (ADR-019 §1): parar de provisionar
   path no MediaMTX central para câmera com agente, e apagar o
   `publish-auth`/RTMP. Toca `api/**` e `infra/mediamtx/**`.
4. **Circuit breaker** no envio à VPS (ADR-019 §5) — toca `edge_agent/**`.
5. Qualquer coisa que precise **testar com a câmera real** ou **regerar o
   `.exe`** (o venv do PyInstaller está aqui).

## Setup do notebook, do zero

### 1. Pré-requisitos

- **Git**
- **Python 3.12** (mesma versão do desktop e dos containers — evita
  divergência de comportamento)
- **Docker Desktop** — opcional, mas necessário para rodar as suítes de teste
  do mesmo jeito que rodam aqui

### 2. Clone

```bash
git clone https://github.com/rafaeldourado9/Next-Sec.git
cd Next-Sec
git checkout perf/edge-low-power
```

O repositório tem ~22 MB de histórico. O modelo YOLO
(`analytics/models/object.pt`, 6,3 MB) **vem no clone** — é o que o benchmark
precisa.

### 3. Modelos que NÃO vêm no clone

Estão no `.gitignore` por tamanho:

| Arquivo | Tamanho | Precisa no notebook? |
|---|---|---|
| `analytics/models/GFPGANv1.4.pth` | 333 MB | **não** |
| `analytics/models/EDSR_x4.pb` | 37 MB | **não** |

Os dois são usados só por `frame_enhance.py` (super-resolução e restauração
facial) — que a ADR-019 §3 manda **desligar** em hardware fraco. Se o
benchmark precisar deles, algo está errado no escopo.

### 4. Ambiente do analytics

Para o benchmark, use **venv nativo, não Docker**. Docker no Windows roda
sobre WSL2, que é uma VM — e medir performance dentro de uma VM para depois
prometer números sobre o hardware do cliente introduz uma variável que não
existe na instalação real.

```bash
cd analytics
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e .
```

`ultralytics` puxa torch (~2 GB de download). É necessário no início — tanto
para o baseline do benchmark quanto para exportar `.pt` → ONNX. A meta é
justamente deixar de precisar dele em runtime.

Para os testes automatizados (não para benchmark), o Docker mantém paridade
com o desktop:

```bash
docker run --rm -v "$PWD/analytics:/app" -w /app next_sec-analytics:latest \
  sh -c "pip install -q pytest pytest-asyncio; python -m pytest -q"
```

(Na primeira vez a imagem precisa ser construída: `docker compose build analytics`.)

### 5. O que o notebook NÃO deve fazer

- **Deploy na VPS.** A chave SSH não está lá, e é melhor assim: um só ponto
  de deploy evita duas pessoas subindo versões diferentes.
- **Regerar o `.exe` do agente.** O venv do PyInstaller e o `ffmpeg.exe`
  empacotado estão no desktop.
- **Mexer em `infra/**` ou `docker-compose.yml`** — território da outra
  frente, e é onde um conflito daria mais trabalho.

## Coordenação entre as duas máquinas

### Branches

```
feat/edge-license-activation   ← integração (estado atual, já no GitHub)
├── perf/edge-low-power        ← notebook
└── ops/vps-hardening          ← desktop (criar quando começar)
```

Cada máquina na sua branch, merge de volta na de integração via PR. **Não
trabalhar as duas na mesma branch** — o conflito não seria de conteúdo, seria
de `git pull` no meio de trabalho não commitado.

Os conjuntos de arquivos quase não se cruzam, o que torna o merge barato:

| Frente | Toca |
|---|---|
| Notebook | `analytics/**` |
| Desktop | `api/**`, `infra/**`, `edge_agent/**`, `native_installer/**`, `docker-compose.yml` |

O único ponto de contato provável é `analytics/src/analytics/core/config.py`
(se ambas as frentes adicionarem configuração). Conflito pequeno, mas vale
avisar antes de mexer.

### Sincronizar

Antes de começar a trabalhar, sempre:

```bash
git fetch origin
git rebase origin/feat/edge-license-activation
```

Isso mantém as duas frentes em cima do mesmo estado e evita um merge grande
no fim.

### Estado atual do projeto

Contexto que vale ler antes de começar em qualquer das duas máquinas:

- [`ADR-019`](../../.genesis/architecture/adrs/019-edge-first-vps-events-only.md)
  — a arquitetura edge-first que orienta as duas frentes
- [`EDGE_PERFORMANCE.md`](EDGE_PERFORMANCE.md) — a agenda do notebook, com o
  método de medição
- [`DEPLOY_VPS.md`](DEPLOY_VPS.md) §8 — as pendências de segurança, a agenda
  do desktop
- `.genesis/memory/progress.md` — histórico detalhado, incluindo os 8 bugs
  reais achados no teste com câmera real

Há **6 testes falhando** na suíte da API desde o Sprint 5
(`roi_schedules`, `channel_adapter`, `notification_contact_dispatch`), nunca
investigados. Não são regressão das mudanças recentes — mas dois deles são de
notificação, que é área crítica. Não confundir com falha nova ao rodar a
suíte pela primeira vez no notebook.
