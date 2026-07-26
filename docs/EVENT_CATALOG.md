# Catálogo de Eventos — VMS White-Label

Documento único e autoritativo de todos os eventos do sistema.
Todo evento novo deve ser adicionado aqui antes de ser implementado.

**Canais:**
- `RabbitMQ` — event bus interno (topic exchange `vms_events`, durable)
- `SSE` — Server-Sent Events para o frontend (via Redis pub/sub)
- `Webhook` — notificação para integrações externas

**Convenção de routing key:** `{dominio}.{acao}` (ex: `camera.online`)

---

## Câmeras

### `camera.created`
**Canal:** RabbitMQ  
**Trigger:** POST /api/v1/cameras/ bem-sucedido  
**Consumidores:** MediaMTX hook (registra path), billing meter
```json
{
  "event": "camera.created",
  "tenant_id": "uuid",
  "camera_id": "uuid",
  "name": "Câmera Entrada",
  "camera_type": "external",
  "rtsp_url": "rtsp://...",
  "timestamp": "2026-05-31T10:00:00Z"
}
```

### `camera.updated`
**Canal:** RabbitMQ  
**Trigger:** PUT /api/v1/cameras/{id}/
```json
{
  "event": "camera.updated",
  "tenant_id": "uuid",
  "camera_id": "uuid",
  "changed_fields": ["name", "location"],
  "timestamp": "2026-05-31T10:00:00Z"
}
```

### `camera.deleted`
**Canal:** RabbitMQ  
**Trigger:** DELETE /api/v1/cameras/{id}/  
**Consumidores:** MediaMTX hook (remove path), storage cleanup
```json
{
  "event": "camera.deleted",
  "tenant_id": "uuid",
  "camera_id": "uuid",
  "timestamp": "2026-05-31T10:00:00Z"
}
```

### `camera.online`
**Canal:** RabbitMQ + SSE  
**Trigger:** agente reporta heartbeat / MediaMTX conecta stream
```json
{
  "event": "camera.online",
  "tenant_id": "uuid",
  "camera_id": "uuid",
  "timestamp": "2026-05-31T10:00:00Z"
}
```
**SSE channel:** `tenant:{tenant_id}:cameras`

### `camera.offline`
**Canal:** RabbitMQ + SSE  
**Trigger:** health check falha / MediaMTX perde stream / heartbeat timeout
```json
{
  "event": "camera.offline",
  "tenant_id": "uuid",
  "camera_id": "uuid",
  "last_seen": "2026-05-31T09:55:00Z",
  "timestamp": "2026-05-31T10:00:00Z"
}
```
**SSE channel:** `tenant:{tenant_id}:cameras`

---

## Gravações

### `recording.segment_ready`
**Canal:** RabbitMQ  
**Trigger:** MediaMTX finaliza segmento de 60s → hook notifica Django  
**Consumidores:** analytics frame extractor, storage indexer
```json
{
  "event": "recording.segment_ready",
  "tenant_id": "uuid",
  "camera_id": "uuid",
  "camera_type": "external",
  "segment_key": "uuid/uuid/2026-05-31/10/seg_42.mp4",
  "duration_seconds": 60,
  "size_bytes": 45000000,
  "started_at": "2026-05-31T10:00:00Z",
  "ended_at": "2026-05-31T10:01:00Z",
  "timestamp": "2026-05-31T10:01:02Z"
}
```

### `recording.exported`
**Canal:** RabbitMQ  
**Trigger:** job de exportação forense concluído
```json
{
  "event": "recording.exported",
  "tenant_id": "uuid",
  "export_id": "uuid",
  "camera_id": "uuid",
  "period_start": "2026-05-31T10:00:00Z",
  "period_end": "2026-05-31T10:30:00Z",
  "export_key": "uuid/forensic/export_id.zip",
  "exported_by": "uuid",
  "timestamp": "2026-05-31T11:00:00Z"
}
```

---

## Detecções ALPR (Fluxo A — câmeras inteligentes)

### `detection.alpr`
**Canal:** RabbitMQ + SSE  
**Trigger:** câmera ANPR envia webhook → FastAPI normaliza → dedup Redis  
**Consumidores:** VmsEvent persister, notification dispatcher, analytics indexer
```json
{
  "event": "detection.alpr",
  "tenant_id": "uuid",
  "camera_id": "uuid",
  "manufacturer": "hikvision",
  "plate": "ABC1D23",
  "confidence": 0.97,
  "vehicle_type": "car",
  "direction": "in",
  "image_key": "uuid/crops/event_id.jpg",
  "raw_payload": {},
  "timestamp": "2026-05-31T10:00:00Z"
}
```
**SSE channel:** `tenant:{tenant_id}:detections`

---

## Analytics (Fluxo B/C — server-side)

### `analytics.motion.detected`
**Canal:** RabbitMQ + SSE  
**Trigger:** plugin motion_detection detecta movimento em frame
```json
{
  "event": "analytics.motion.detected",
  "tenant_id": "uuid",
  "camera_id": "uuid",
  "analytic_event_id": "uuid",
  "zone_id": "uuid-or-null",
  "confidence": 0.82,
  "bbox": [120, 80, 300, 200],
  "thumbnail_key": "uuid/crops/event_id.jpg",
  "segment_key": "uuid/uuid/2026-05-31/10/seg_42.mp4",
  "occurred_at": "2026-05-31T10:00:30Z",
  "timestamp": "2026-05-31T10:00:31Z"
}
```

### `analytics.person.detected`
**Canal:** RabbitMQ + SSE
```json
{
  "event": "analytics.person.detected",
  "tenant_id": "uuid",
  "camera_id": "uuid",
  "analytic_event_id": "uuid",
  "confidence": 0.91,
  "bbox": [150, 60, 280, 400],
  "attributes": {
    "color_top": "azul",
    "color_bottom": "preto",
    "clothing_type": "casual"
  },
  "thumbnail_key": "uuid/crops/event_id.jpg",
  "segment_key": "uuid/uuid/2026-05-31/10/seg_42.mp4",
  "occurred_at": "2026-05-31T10:00:30Z",
  "timestamp": "2026-05-31T10:00:31Z"
}
```

### `analytics.vehicle.detected`
**Canal:** RabbitMQ + SSE
```json
{
  "event": "analytics.vehicle.detected",
  "tenant_id": "uuid",
  "camera_id": "uuid",
  "analytic_event_id": "uuid",
  "confidence": 0.88,
  "bbox": [50, 100, 400, 300],
  "attributes": {
    "vehicle_type": "car",
    "color": "branco"
  },
  "thumbnail_key": "uuid/crops/event_id.jpg",
  "segment_key": "uuid/uuid/2026-05-31/10/seg_42.mp4",
  "occurred_at": "2026-05-31T10:00:30Z",
  "timestamp": "2026-05-31T10:00:31Z"
}
```

### `analytics.intrusion.detected`
**Canal:** RabbitMQ + SSE + Alarm trigger
```json
{
  "event": "analytics.intrusion.detected",
  "tenant_id": "uuid",
  "camera_id": "uuid",
  "analytic_event_id": "uuid",
  "zone_id": "uuid",
  "zone_name": "Área Restrita Norte",
  "confidence": 0.94,
  "thumbnail_key": "uuid/crops/event_id.jpg",
  "segment_key": "uuid/uuid/2026-05-31/10/seg_42.mp4",
  "occurred_at": "2026-05-31T10:00:30Z",
  "timestamp": "2026-05-31T10:00:31Z"
}
```

### `analytics.lpr.detection`
**Canal:** RabbitMQ + SSE  
**Trigger:** plugin lpr_parking detecta placa via OCR server-side (Fluxo B — câmera burra)
```json
{
  "event": "analytics.lpr.detection",
  "tenant_id": "uuid",
  "camera_id": "uuid",
  "analytic_event_id": "uuid",
  "plate": "DEF4G56",
  "confidence_detection": 0.91,
  "confidence_ocr": 0.88,
  "vehicle_type": "car",
  "image_key": "uuid/crops/event_id.jpg",
  "segment_key": "uuid/uuid/2026-05-31/10/seg_42.mp4",
  "occurred_at": "2026-05-31T10:00:30Z",
  "timestamp": "2026-05-31T10:00:31Z"
}
```

### `analytics.face.recognized`
**Canal:** RabbitMQ (NÃO SSE — dados biométricos)  
**Gate:** somente com LGPDConsent ativo
```json
{
  "event": "analytics.face.recognized",
  "tenant_id": "uuid",
  "camera_id": "uuid",
  "analytic_event_id": "uuid",
  "face_profile_id": "uuid-or-null",
  "similarity": 0.87,
  "image_key": "uuid/faces/event_id.jpg.enc",
  "segment_key": "uuid/uuid/2026-05-31/10/seg_42.mp4",
  "occurred_at": "2026-05-31T10:00:30Z",
  "timestamp": "2026-05-31T10:00:31Z"
}
```
⚠️ **Nunca publicar via SSE** — dados biométricos não vão para o browser diretamente.

### `analytics.weapon.detected`
**Canal:** RabbitMQ + SSE + Alarm trigger (severity: critical)  
**Status:** Beta — alta taxa de falso positivo
```json
{
  "event": "analytics.weapon.detected",
  "tenant_id": "uuid",
  "camera_id": "uuid",
  "analytic_event_id": "uuid",
  "confidence": 0.73,
  "weapon_type": "unknown",
  "bbox": [200, 150, 280, 320],
  "thumbnail_key": "uuid/crops/event_id.jpg",
  "segment_key": "uuid/uuid/2026-05-31/10/seg_42.mp4",
  "occurred_at": "2026-05-31T10:00:30Z",
  "timestamp": "2026-05-31T10:00:31Z"
}
```

---

## Agentes

### `agent.created`
**Canal:** RabbitMQ
```json
{
  "event": "agent.created",
  "tenant_id": "uuid",
  "agent_id": "uuid",
  "name": "Agente Sede",
  "timestamp": "2026-05-31T10:00:00Z"
}
```

### `agent.heartbeat`
**Canal:** RabbitMQ + SSE
```json
{
  "event": "agent.heartbeat",
  "tenant_id": "uuid",
  "agent_id": "uuid",
  "version": "1.2.3",
  "cameras_active": 12,
  "timestamp": "2026-05-31T10:00:00Z"
}
```
**SSE channel:** `tenant:{tenant_id}:agents`

### `agent.revoked`
**Canal:** RabbitMQ
```json
{
  "event": "agent.revoked",
  "tenant_id": "uuid",
  "agent_id": "uuid",
  "revoked_by": "uuid",
  "timestamp": "2026-05-31T10:00:00Z"
}
```

---

## Tenants (Admin)

### `tenant.created`
**Canal:** RabbitMQ  
**Consumidores:** Redis namespace setup, MinIO prefix setup, email worker
```json
{
  "event": "tenant.created",
  "tenant_id": "uuid",
  "name": "Cliente Integrador XYZ",
  "gestor_id": "uuid",
  "plan_id": "uuid",
  "created_by_admin": "uuid",
  "timestamp": "2026-05-31T10:00:00Z"
}
```

### `tenant.suspended`
**Canal:** RabbitMQ  
**Consumidores:** JWT blacklist worker
```json
{
  "event": "tenant.suspended",
  "tenant_id": "uuid",
  "suspended_by": "uuid",
  "reason": "Inadimplência",
  "timestamp": "2026-05-31T10:00:00Z"
}
```

### `tenant.reactivated`
**Canal:** RabbitMQ
```json
{
  "event": "tenant.reactivated",
  "tenant_id": "uuid",
  "reactivated_by": "uuid",
  "timestamp": "2026-05-31T10:00:00Z"
}
```

---

## Billing

### `billing.invoice.generated`
**Canal:** RabbitMQ  
**Consumidores:** notification dispatcher (email ao Gestor)
```json
{
  "event": "billing.invoice.generated",
  "tenant_id": "uuid",
  "invoice_id": "uuid",
  "period_start": "2026-05-01",
  "period_end": "2026-05-31",
  "total": "1250.00",
  "due_date": "2026-06-30",
  "timestamp": "2026-06-01T06:00:00Z"
}
```

### `billing.invoice.paid`
**Canal:** RabbitMQ
```json
{
  "event": "billing.invoice.paid",
  "tenant_id": "uuid",
  "invoice_id": "uuid",
  "payment_id": "uuid",
  "amount": "1250.00",
  "method": "pix",
  "recorded_by": "uuid",
  "timestamp": "2026-05-31T10:00:00Z"
}
```

---

## Notificações

### `notification.sent`
**Canal:** RabbitMQ
```json
{
  "event": "notification.sent",
  "tenant_id": "uuid",
  "rule_id": "uuid",
  "trigger_event": "camera.offline",
  "channel": "webhook",
  "destination": "https://central.exemplo.com/webhook",
  "status": "delivered",
  "status_code": 200,
  "timestamp": "2026-05-31T10:00:00Z"
}
```

### `notification.failed`
**Canal:** RabbitMQ
```json
{
  "event": "notification.failed",
  "tenant_id": "uuid",
  "rule_id": "uuid",
  "channel": "webhook",
  "destination": "https://central.exemplo.com/webhook",
  "error": "Connection timeout",
  "attempt": 2,
  "timestamp": "2026-05-31T10:00:00Z"
}
```

---

## Alarmes

### `alarm.triggered`
**Canal:** RabbitMQ + SSE
```json
{
  "event": "alarm.triggered",
  "tenant_id": "uuid",
  "alarm_id": "uuid",
  "alarm_type": "intrusion",
  "severity": "high",
  "camera_id": "uuid",
  "source_event_id": "uuid",
  "timestamp": "2026-05-31T10:00:00Z"
}
```
**SSE channel:** `tenant:{tenant_id}:alarms`

### `alarm.acknowledged`
**Canal:** RabbitMQ + SSE
```json
{
  "event": "alarm.acknowledged",
  "tenant_id": "uuid",
  "alarm_id": "uuid",
  "acknowledged_by": "uuid",
  "notes": "Falso alarme — manutenção autorizada",
  "timestamp": "2026-05-31T10:05:00Z"
}
```

---

## Auditoria

### `audit.*` (todos os eventos de auditoria)
**Canal:** RabbitMQ somente (nunca SSE)  
**Queue:** `q.audit_writer` (worker dedicado append-only)

Ver tabela completa de ações em `docs/MASTER_PLAN.md` seção "Auditoria".

---

## Canais SSE por tenant

| Channel Redis Key | Eventos publicados |
|------------------|--------------------|
| `tenant:{id}:cameras` | camera.online, camera.offline |
| `tenant:{id}:detections` | detection.alpr |
| `tenant:{id}:analytics` | analytics.motion, analytics.person, analytics.vehicle, analytics.intrusion, analytics.lpr |
| `tenant:{id}:agents` | agent.heartbeat |
| `tenant:{id}:alarms` | alarm.triggered, alarm.acknowledged |

**Nota:** `analytics.face.recognized` e `analytics.weapon.detected` NÃO são publicados via SSE diretamente — passam por processamento de alarme antes.
