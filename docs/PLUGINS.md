# VMS MVP — Analytics Plugins

> Versao: 2.0 · Data: 2026-04-12
> Servico: analytics/ (FastAPI + YOLOv8)

---

## 1. Visao Geral

O Analytics Service e um servico independente que roda plugins de deteccao
sobre frames RTSP das cameras. Nao depende do VMS API em tempo de execucao
(exceto para discovery de cameras e ROIs via HTTP).

```
+----------------------------+
|    Analytics Service       |
|                            |
|  Orchestrator              |
|    |-- load_plugins()      |    GET /plugins/cameras
|    |-- start()  ---------> |  -----------------> VMS API
|    |                       |    GET /plugins/rois
|    v                       |  -----------------> VMS API
|  Per camera (async task):  |
|    FrameSource (RTSP)      |    rtsp://mediamtx:8554/{path}
|    |-- read() 1fps         |  -----------------> MediaMTX
|    v                       |
|  Plugins (process_frame)   |
|    |-- Intrusion           |
|    |-- PeopleCount         |    POST /plugins/events
|    |-- VehicleCount        |  -----------------> VMS API
|    |-- LPR                 |
|    |-- FireSmoke           |
|    |-- PPE                 |
|    |-- Biker               |
|    +-- HorseCart           |
+----------------------------+
```

---

## 2. Catalogo de Plugins

| # | ID | Nome | Categoria | Modelo | Tamanho | FPS | ROI obrigatorio |
|---|-----|------|-----------|--------|---------|-----|-----------------|
| 1 | intrusion | Intrusion Detection | security | YOLOv8n (object.pt) | 3.2 MB | 1 | Sim |
| 2 | people_count | People Counting | traffic | YOLOv8n (object.pt) | 3.2 MB | 1 | Sim |
| 3 | vehicle_count | Vehicle Counting | traffic | YOLOv8n (object.pt) | 3.2 MB | 1 | Sim |
| 4 | fire_smoke | Fire & Smoke | safety | Custom (fire.pt) | 49.7 MB | 2 | Opcional |
| 5 | ppe_detection | PPE Detection | safety | Custom (ppe.pt) | 6.0 MB | 3 | Opcional |
| 6 | biker_detection | Biker Helmet | traffic | Custom (biker_2.pt) | 6.0 MB | 2 | Opcional |
| 7 | lpr | License Plate (LPR) | security | YOLO + fast-plate-ocr | 6.2 MB | 4 | Sim |
| 8 | horse_cart | Horse & Cart | custom | Custom (horse_cart.pt) | 49.6 MB | 2 | Opcional |

---

## 3. Configuracao de ROI por Plugin

### intrusion
```json
{
  "min_confidence": 0.5,
  "cooldown_seconds": 30
}
```
- Detecta classes COCO (default: person=0)
- Emite evento se centroid do bbox esta dentro do poligono
- Cooldown impede emissao repetida (debounce)
- Evento: `analytics.intrusion.detected`

### people_count
```json
{
  "min_confidence": 0.5,
  "interval_seconds": 60,
  "emit_threshold": 0
}
```
- Conta pessoas (COCO class 0) dentro do poligono
- Emite se contagem > threshold, respeitando intervalo
- Evento: `analytics.people.count`

### vehicle_count
```json
{
  "min_confidence": 0.5,
  "interval_seconds": 60,
  "emit_threshold": 0
}
```
- Conta veiculos (car=2, motorcycle=3, bus=5, truck=7)
- Mesma logica de people_count
- Evento: `analytics.vehicle.count`

### lpr
```json
{
  "min_plate_confidence": 0.7,
  "min_ocr_confidence": 0.6,
  "dedup_ttl_seconds": 60
}
```
- Detecta bbox da placa com YOLO
- OCR com fast-plate-ocr (formato BR: AAA1234 ou AAA1A23)
- Centroid deve estar dentro do poligono ROI
- Dedup por placa+camera dentro do TTL
- Evento: `analytics.lpr.detected`

### fire_smoke / ppe_detection / biker_detection / horse_cart
```json
{}
```
- Sem configuracao adicional obrigatoria
- ROI opcional — sem ROI, detecta no frame inteiro
- Eventos: `analytics.fire_smoke.detected`, `analytics.ppe.detected`, etc.

---

## 4. Interface do Plugin

```python
class AnalyticsPlugin(ABC):
    name: str           # "intrusion_detection"
    version: str        # "1.0.0"
    roi_type: str       # "intrusion"

    async def initialize(self, config: dict) -> None:
        """Carrega modelo, aloca recursos."""

    @abstractmethod
    async def process_frame(
        self,
        frame: np.ndarray,         # RGB (H x W x 3)
        metadata: FrameMetadata,   # camera_id, tenant_id, timestamp
        rois: list[ROIConfig],     # Zonas ativas para esta camera
    ) -> list[AnalyticsResult]:
        """Processa frame e retorna deteccoes."""

    async def shutdown(self) -> None:
        """Libera recursos."""
```

### Dataclasses

```python
@dataclass
class ROIConfig:
    id: str
    name: str
    ia_type: str                          # Plugin type
    polygon_points: list[list[float]]     # Normalizado [0.0-1.0]
    config: dict                          # Config especifica do plugin

@dataclass
class FrameMetadata:
    camera_id: str
    tenant_id: str
    timestamp: datetime
    stream_url: str

@dataclass
class AnalyticsResult:
    plugin: str
    camera_id: str
    tenant_id: str
    event_type: str
    payload: dict
    occurred_at: datetime
    confidence: float | None = None
    roi_id: str | None = None
```

### YOLOPlugin (base para plugins YOLO)

```python
class YOLOPlugin(AnalyticsPlugin):
    def detect(frame, conf, classes) -> list[dict]
    def point_in_polygon(point, polygon) -> bool
    def filter_in_roi(detections, polygon) -> list[dict]
    def centroid(bbox) -> tuple[float, float]
```

---

## 5. Como Criar um Novo Plugin

1. Criar diretorio `analytics/src/analytics/plugins/{nome}/`
2. Criar `plugin.py` com classe que herda `YOLOPlugin` ou `AnalyticsPlugin`
3. Definir `name`, `version`, `roi_type`
4. Implementar `process_frame()`
5. (Opcional) Colocar modelo custom em `analytics/models/`
6. O orchestrator descobre automaticamente via scan de diretorio

Exemplo minimo:

```python
# analytics/src/analytics/plugins/my_plugin/plugin.py
from analytics.core.yolo_base import YOLOPlugin
from analytics.core.plugin_base import AnalyticsResult, FrameMetadata, ROIConfig
import numpy as np

class MyPlugin(YOLOPlugin):
    name = "my_plugin"
    version = "1.0.0"
    roi_type = "my_zone"

    async def process_frame(
        self,
        frame: np.ndarray,
        metadata: FrameMetadata,
        rois: list[ROIConfig],
    ) -> list[AnalyticsResult]:
        detections = self.detect(frame, conf=0.5, classes=[0])
        results = []
        for roi in rois:
            if roi.ia_type != self.roi_type:
                continue
            in_roi = self.filter_in_roi(detections, roi.polygon_points)
            if in_roi:
                results.append(AnalyticsResult(
                    plugin=self.name,
                    camera_id=metadata.camera_id,
                    tenant_id=metadata.tenant_id,
                    event_type="analytics.my_plugin.detected",
                    payload={"count": len(in_roi), "detections": in_roi},
                    occurred_at=metadata.timestamp,
                    confidence=max(d["confidence"] for d in in_roi),
                    roi_id=roi.id,
                ))
        return results
```

---

## 6. Variaveis de Ambiente

| Variavel | Default | Descricao |
|----------|---------|-----------|
| VMS_API_URL | http://localhost:8000 | URL da API VMS |
| VMS_API_KEY | dev-analytics-key | API key para auth |
| MEDIAMTX_HOST | mediamtx | Hostname RTSP |
| MEDIAMTX_RTSP_PORT | 8554 | Porta RTSP |
| ANALYTICS_FPS | 1 | Frames por segundo por camera |
| ANALYTICS_WORKERS | 4 | Workers paralelos |
| YOLO_IMGSZ | 640 | Tamanho de inferencia YOLO |
| YOLO_CONF | 0.30 | Threshold de confianca |
| YOLO_MODEL_PATH | /models/object.pt | Modelo YOLO padrao |
| FIRE_SMOKE_MODEL_PATH | /models/fire.pt | Modelo fire/smoke |
| PPE_MODEL_PATH | /models/ppe.pt | Modelo PPE |
| BIKER_MODEL_PATH | /models/biker_2.pt | Modelo biker |
| HORSE_CART_MODEL_PATH | /models/horse_cart.pt | Modelo horse/cart |
| LPR_MODEL_PATH | /models/object.pt | Detector de placa |
| LOG_LEVEL | INFO | Nivel de log |

---

## 7. Fallback Local (zones.yaml)

Se o analytics service nao consegue acessar a API para ROIs, carrega config local:

```yaml
# zones.yaml
cam-123:
  - id: "zone-1"
    name: "Entrada"
    ia_type: "intrusion"
    polygon_points: [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
    config:
      min_confidence: 0.5
      cooldown_seconds: 30
```

Ou via variavel: `PLUGIN_ZONES_JSON='{"cam-123": [...]}'`

---

## 8. Health Check

```
GET http://analytics:8001/health

Response:
{
  "status": "healthy",
  "plugins_loaded": 8,
  "plugin_names": [
    "intrusion_detection", "people_count", "vehicle_count",
    "lpr", "fire_smoke", "ppe_detection",
    "biker_detection", "horse_cart"
  ]
}
```

---

## 9. Dependencias

```
fastapi, uvicorn          -> API + lifespan
httpx                     -> HTTP client para VMS API
ultralytics               -> YOLOv8 inferencia
opencv-python-headless    -> RTSP stream + frame capture
fast-plate-ocr            -> OCR de placas (plugin LPR)
numpy                     -> Manipulacao de frames
pydantic, pydantic-settings -> Config e schemas
structlog                 -> Logging estruturado
redis                     -> Cache opcional
```

GPU: Dockerfile suporta CUDA 12.4 (nvidia). CPU funciona sem GPU (mais lento).
