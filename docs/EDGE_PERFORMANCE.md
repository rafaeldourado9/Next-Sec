# Performance do edge — 16 câmeras em 8 GB sem GPU

Alvo declarado pela [ADR-019](../../.genesis/architecture/adrs/019-edge-first-vps-events-only.md)
§3: **16 câmeras, 8 GB de RAM, sem GPU**, num PC comum de cliente.

Este documento é o *como*. A decisão de que esse alvo é obrigatório (e não
"melhor esforço") está na ADR.

> **Aviso sobre os números abaixo:** as estimativas de tempo de inferência e
> de memória são **projeções**, não medições. Ninguém rodou isso no hardware
> alvo ainda. A seção "Como medir" existe justamente para substituir estas
> estimativas por números reais antes de qualquer promessa comercial. Trate
> as ordens de grandeza como orientação de prioridade, não como spec.

## O problema, em números

Configuração atual (`analytics/core/`): `ultralytics.YOLO` sobre `.pt`,
PyTorch FP32, `yolo_imgsz=640`, inferência em **todo frame amostrado**.

Estimativa de custo por inferência nessa configuração, numa CPU modesta de 4
núcleos: ~150–250 ms. Com 16 câmeras a 1 fps, isso demanda ~3 núcleos apenas
para inferência — antes de decodificar qualquer vídeo. Inviável.

O caminho até viabilidade é multiplicativo, e cada etapa abaixo ataca um
fator diferente.

## O que já existe (não refazer)

| Técnica | Onde | Efeito |
|---|---|---|
| **Substream para análise** | `orchestrator.py::_prefer_substream` | Reescreve Hikvision `Channels/101` → `102`. Analisar 480p em vez de 1080p corta o decode em ~6× |
| **Amostragem de frames** | `frame_source.py`, `analytics_fps` (default 1) | `grab()` descarta frames sem fazer a conversão de cor/cópia para numpy |
| **Inferência compartilhada** | `shared_inference.py` | 1 forward do YOLO alimenta N plugins, em vez de um por plugin |
| **Leitura via MediaMTX local** | `orchestrator.py::_build_mediamtx_rtsp` | Evita abrir uma **segunda** conexão RTSP na câmera. Importa mais do que parece: câmeras Hikvision domésticas engasgam com dois clientes simultâneos (visto em teste real) |
| **Cache de detecção** | `detection_cache.py` | Pula o trabalho dos **plugins** em sequências de frames vazios, preservando "intruso parado" |

## O que falta — em ordem de impacto

### 1. Gating de movimento antes da inferência

**O maior item.** Hoje o `DetectionCache` decide *depois* do YOLO — usa o
resultado da inferência como chave. O custo dominante já foi pago quando ele
age.

Introduzir uma etapa barata antes:

- Diferença de frames em escala de cinza, restrita à ROI da câmera.
- Custo: ~1–2 ms por frame em 480p (contra ~200 ms de uma inferência).
- Em cena de vigilância típica, a grande maioria dos frames não tem
  movimento relevante.

Efeito: a taxa de inferência deixa de ser "1/s × 16 câmeras" e passa a
acompanhar o movimento real na cena.

**Não remove o `DetectionCache`.** Ele resolve um caso que o gating de
movimento perderia: um intruso **parado** não gera diferença entre frames,
mas continua sendo uma detecção válida. Movimento decide se vale *olhar*;
detecção decide se vale *reagir*.

### 2. ONNX Runtime INT8 a 320 px, em vez de PyTorch FP32 a 640 px

Três ganhos empilhados, todos no mesmo lugar:

| Mudança | Fator estimado |
|---|---|
| PyTorch → ONNX Runtime | ~2× |
| FP32 → INT8 (quantização) | ~2–3× |
| `imgsz` 640 → 320 | ~4× (área) |

`onnxruntime` **já está nas dependências** (`analytics/pyproject.toml`).

Ganho colateral igualmente importante: **remover o torch da memória
residente**. Só o torch ocupa ~1 GB — num orçamento de 8 GB, isso sozinho
justifica a migração.

Sobre `imgsz=320`: para detectar pessoa/veículo a distâncias típicas de
vigilância, costuma ser suficiente. É exatamente o tipo de coisa que a etapa
de medição precisa confirmar — se a taxa de detecção cair demais numa câmera
específica, `imgsz` é configurável por câmera.

### 3. Perfil de hardware fraco (forçar desligado)

O que precisa estar **desligado por padrão** neste perfil, não por
configuração manual:

- **`frame_enhance.py`** — FSRCNN, EDSR, GFPGAN (super-resolução e
  restauração facial). Em CPU custa *segundos* por frame. É a diferença
  entre funcionar e travar.
- **Reconhecimento facial (InsightFace) em todas as câmeras** — habilitável
  só por câmera específica, e ainda sujeito ao gate de consentimento LGPD já
  existente (`tenant.facial_recognition_enabled`, ADR-014).

O objetivo é que a primeira instalação num PC de 8 GB falhe no laboratório,
não no cliente.

## Orçamento de memória

16 câmeras, 8 GB:

| Componente | Estimativa |
|---|---|
| Windows | 2,0–2,5 GB |
| MediaMTX (16 streams, *stream copy*) | ~300 MB |
| Analytics com ONNX INT8, **sem torch** | ~700 MB |
| **Subtotal de serviços** | **~3,5 GB** |
| Navegador com 16 streams | 1,5–2,5 GB |
| **Total com visualização aberta** | **~5–6 GB** |

Cabe, com folga apertada. O navegador é o componente mais pesado.

Mitigações para a visualização (ADR-019 §1 — a interface roda localmente):

- **Grade sempre em substream** (16 × 480p). Mainstream só ao abrir uma
  câmera em tela cheia. É o que todo VMS comercial faz.
- **Decodificação por hardware** no navegador (QuickSync/NVDEC/VAAPI conforme
  a máquina).

Se o torch **não** for removido, some ~1 GB à linha de analytics e o
orçamento deixa de fechar com a visualização aberta.

## Custo de gravação

Praticamente zero em CPU, e é assim que precisa continuar: o MediaMTX grava
em ***stream copy*** — sem decodificar nem reencodar, só multiplexando os
pacotes que já chegam da câmera.

Buffer circular (ADR-019 §2): `recordDeleteAfter: 2m`. Disco em regime
estável ≈ **500 MB** para 16 câmeras a 2 Mbps.

O único reencode do sistema é o clipe de 15 s enviado à VPS (480p, ADR-018
§4) — um por evento, não contínuo.

## Como medir (antes de prometer 16 câmeras)

Esta seção substitui as estimativas acima por números reais. Fazer **no
hardware alvo**, não numa máquina de desenvolvimento.

**1. Benchmark de inferência** — o número que define tudo:

Comparar, no mesmo hardware e com o mesmo conjunto de frames reais:
- PyTorch FP32 `imgsz=640` (configuração atual)
- ONNX Runtime FP32 `imgsz=640`
- ONNX Runtime INT8 `imgsz=320`

Medir latência média por frame e memória residente do processo. O
orçamento por câmera é `1 / analytics_fps` segundos dividido pelo número de
câmeras que compartilham o núcleo.

**2. Taxa real de movimento** — define o ganho do gating:

Instrumentar por algumas horas, com as câmeras do cliente na cena real, qual
fração dos frames passa no gate de movimento. É esse número, não uma
estimativa genérica, que diz quantas inferências por segundo realmente
acontecem.

**3. Decode sob carga** — 16 streams simultâneos:

Medir uso de CPU com as 16 câmeras conectadas, **sem** inferência, para
isolar o custo de decode do custo de análise.

**4. Memória em regime** — com visualização aberta:

Deixar rodando algumas horas com a grade de 16 câmeras aberta no navegador e
observar se há crescimento (vazamento) além do platô esperado.

## Resumo da ordem de trabalho

1. **Medir** (seção acima) — define se o alvo é 16 câmeras ou menos.
2. **ONNX INT8 + `imgsz` 320** — maior ganho isolado, e libera ~1 GB de RAM.
3. **Gating de movimento** — maior ganho estrutural na taxa de inferência.
4. **Perfil de hardware fraco** — impede que a instalação trave no cliente.

Os itens 2 e 3 são independentes e podem ser feitos em paralelo.
