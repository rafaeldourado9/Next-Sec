# Tarefas — branch `perf/edge-low-power` (notebook)

Agenda de performance do edge. Contexto e racional em
[`EDGE_PERFORMANCE.md`](EDGE_PERFORMANCE.md); setup da máquina e divisão do
trabalho em [`PLANO_DEV_NOTEBOOK.md`](PLANO_DEV_NOTEBOOK.md).

**Meta da branch:** responder com números medidos se o alvo da
[ADR-019](../../.genesis/architecture/adrs/019-edge-first-vps-events-only.md)
§3 — **16 câmeras, 8 GB, sem GPU** — é atingível, e implementar as técnicas
que o tornam atingível.

**Regra que vale para tudo aqui:** nenhuma conclusão de performance sem
medição no hardware alvo. Os números que estão hoje no `EDGE_PERFORMANCE.md`
são estimativas minhas, rotuladas como tal — a primeira entrega desta branch
é substituí-los por medições reais.

---

## Fase 0 — Insumo (bloqueia T1)

### T0. Obter footage de referência
- [ ] Um arquivo de vídeo fixo, representativo de cena de vigilância, para
      todo benchmark rodar sobre o mesmo conjunto de frames.

**Por que arquivo e não câmera ao vivo:** comparação justa entre backends
exige entrada idêntica. Câmera ao vivo muda a cada execução — qualquer
diferença medida ficaria confundida com variação de cena.

**Requisitos:** ~2–5 min, com pessoas/veículos entrando e saindo, e pelo
menos um trecho com **pessoa parada** (caso que o `DetectionCache` existe
para resolver e que o gating de movimento sozinho perderia — ver T6).

Opções: gravar da câmera Hikvision no desktop (`ffmpeg -rtsp_transport tcp
-i <rtsp> -t 300 -c copy amostra.mp4`), ou qualquer footage de vigilância
pública. **Não commitar no repositório** — deixar fora do git e referenciar
por caminho, para não inflar o clone.

---

## Fase 1 — Medir (define todo o resto)

### T1. Harness de benchmark
- [ ] Script reprodutível que roda inferência sobre o arquivo do T0 e reporta
      latência (p50 e p95), memória residente do processo e uso de CPU.

**Onde:** novo, sugestão `analytics/benchmarks/bench_inference.py`.
Reaproveitar `analytics/core/file_frame_source.py`, que já lê de arquivo.

**Aceitação:** roda com um comando, imprime tabela, e duas execuções seguidas
dão números consistentes (variação pequena entre elas). Sem isso, qualquer
comparação posterior é ruído.

### T2. Baseline da configuração atual
- [ ] Medir PyTorch FP32 `imgsz=640` (o que está em produção hoje).

**Aceitação:** número de latência por frame **e** memória residente
registrados. A memória importa tanto quanto a latência — é o argumento para
tirar o torch.

### T3. Substituir as estimativas por medições
- [ ] Atualizar a tabela do `EDGE_PERFORMANCE.md` com os números reais e
      remover o aviso de "são estimativas" das linhas já medidas.

**Aceitação:** fica explícito no documento o que foi medido, em que hardware
e com que footage. Um número sem essas três informações não é reprodutível.

---

## Fase 2 — Inferência (maior ganho isolado)

### T4. Exportar ONNX e quantizar INT8
- [ ] `object.pt` → ONNX (via ultralytics) → INT8 (via
      `onnxruntime.quantization`).

**Aceitação — e este é o ponto delicado:** medir não só velocidade, mas
**paridade de detecção**. Quantização INT8 pode degradar acurácia. Comparar,
sobre o mesmo footage, quantas detecções cada backend produz e com que
confiança. Ganho de 3× que perde 30% das detecções não é ganho, é regressão
disfarçada — e num sistema de segurança, detecção perdida é o pior tipo de
falha.

### T5. Backend ONNX no `SharedInferenceEngine`
- [ ] Trocar `ultralytics.YOLO` por ONNX Runtime, atrás de configuração, com
      o caminho PyTorch ainda disponível como fallback.

**Onde:** `analytics/src/analytics/core/shared_inference.py`,
`core/yolo_base.py`, `core/config.py`.

**Aceitação:** suíte do analytics passando (22 testes hoje), e o resultado da
inferência equivalente ao do backend antigo sobre o mesmo frame.

### T6. Validar `imgsz=320`
- [ ] Medir ganho de velocidade **e** impacto na detecção a distâncias
      típicas de vigilância.

**Aceitação:** se a detecção cair demais em alguma distância, `imgsz` vira
configurável por câmera em vez de global. Documentar o limite encontrado —
"funciona até X metros" é informação de produto, não detalhe interno.

### T7. Remover torch do runtime
- [ ] Depois que T5 estiver estável, tirar `ultralytics`/torch das
      dependências de execução (podem ficar como dependência de
      desenvolvimento, para a exportação do T4).

**Aceitação:** memória residente medida antes e depois. A expectativa é
~1 GB — confirmar. É o que decide se a visualização de 16 câmeras cabe junto
no orçamento de 8 GB.

---

## Fase 3 — Gating (maior ganho estrutural)

### T8. Gating de movimento antes da inferência
- [ ] Diferença de frames em escala de cinza, restrita à ROI, decidindo se
      vale rodar o YOLO.

**Onde:** módulo novo em `analytics/core/`, ligado no `orchestrator.py` antes
da chamada de inferência.

**Aceitação — duas coisas, e a segunda é a que importa:**
1. Reduz a taxa de inferência sobre o footage do T0 (medir a fração de frames
   que passa no gate).
2. **Pessoa parada continua sendo detectada.** O gating sozinho perderia
   esse caso — é exatamente o que o `DetectionCache` resolve. Os dois têm que
   conviver: movimento decide se vale *olhar*, detecção decide se vale
   *reagir*. Um teste com o trecho de pessoa parada do T0 é obrigatório.

### T9. Medir taxa real de movimento
- [ ] Instrumentar a fração de frames que passa no gate, em cena real, por
      algumas horas.

**Aceitação:** é esse número — não uma estimativa genérica — que diz quantas
inferências por segundo realmente acontecem, e portanto quantas câmeras
cabem. Fecha a pergunta que abriu a branch.

---

## Fase 4 — Proteção

### T10. Perfil de hardware fraco
- [ ] Perfil de configuração que **força** desligados:
      `frame_enhance` (FSRCNN/EDSR/GFPGAN) e reconhecimento facial em todas
      as câmeras.

**Por que forçar e não documentar:** em CPU, `frame_enhance` custa segundos
por frame. Se depender de alguém lembrar de configurar, a primeira
instalação num PC de 8 GB trava — e trava no cliente, não no laboratório.

**Aceitação:** com o perfil ativo, tentar habilitar qualquer um dos dois
falha de forma visível (log claro), não silenciosamente.

---

## Definição de pronto (branch inteira)

- [ ] `EDGE_PERFORMANCE.md` sem estimativas não medidas nas seções cobertas.
- [ ] Resposta com número para: **quantas câmeras cabem em 8 GB sem GPU?**
      Se não forem 16, dizer quantas — e a ADR-019 §"Quando revisar" manda
      ajustar o alvo declarado para baixo, não deixar a promessa desalinhada
      da realidade.
- [ ] Suíte do analytics passando (22 testes hoje).
- [ ] Paridade de detecção verificada entre backend antigo e novo — não só
      velocidade.

---

## Ordem e dependências

```
T0 ──> T1 ──> T2 ──> T3
              │
              ├──> T4 ──> T5 ──> T6 ──> T7      (inferência)
              │
              └──> T8 ──> T9                    (gating)

T10 é independente — pode ser feita a qualquer momento.
```

T4–T7 e T8–T9 são independentes entre si depois do T1: dá para alternar entre
as duas se uma travar.

**Não comece por T4.** Sem o baseline do T2, não há como saber se a migração
melhorou nada — e a resposta "melhorou 3×" sem número de partida não
convence ninguém, inclusive você mesmo daqui a um mês.
