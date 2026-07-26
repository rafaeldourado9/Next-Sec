# 🎯 Backend Analytics - Implementação Completa

## ✅ O Que Foi Criado

### 1. Database Models (`api/src/vms/analytics/models.py`)

**`PluginInstallation`** — Plugins instalados nos edge agents
- `id`, `plugin_id`, `plugin_name`, `version`
- `edge_agent_id`, `tenant_id`
- `status` (installed | running | stopped | error)
- `settings` (JSON), `model_path`, `fps_target`
- `created_at`, `updated_at`

**`AnalyticsEvent`** — Eventos gerados pelos plugins
- `id`, `plugin_installation_id` (FK), `tenant_id`
- `camera_id`, `camera_name`, `plugin_id`
- `event_type`, `severity` (critical | warning | info)
- `confidence`, `payload` (JSON)
- `snapshot_path`, `occurred_at`, `created_at`

### 2. Service Layer (`api/src/vms/analytics/service.py`)

**`AnalyticsService`** com métodos:

| Método | Descrição |
|--------|-----------|
| `list_installations(tenant_id)` | Lista plugins do tenant |
| `create_installation(...)` | Registra instalação de plugin |
| `update_installation_status(id, status)` | Atualiza status (start/stop) |
| `delete_installation(id)` | Remove plugin |
| `create_event(...)` | Cria evento de detecção |
| `list_events(...)` | Lista eventos com filtros |
| `get_event_stats(tenant_id, hours)` | Estatísticas para dashboard |

### 3. API Router (`api/src/vms/analytics/router.py`)

**Endpoints implementados:**

#### Catálogo de Plugins
```
GET    /api/v1/analytics/catalog           → Lista todos os plugins disponíveis
GET    /api/v1/analytics/catalog/{id}      → Detalhes de um plugin
```

#### Instalação/Gestão
```
POST   /api/v1/analytics/install           → Instala plugin no edge agent
GET    /api/v1/analytics/installations     → Lista plugins instalados
DELETE /api/v1/analytics/installations/{id} → Remove plugin
PATCH  /api/v1/analytics/installations/{id}/status → Start/Stop plugin
```

#### Eventos
```
POST   /api/v1/analytics/events            → Cria evento (edge agent → VMS)
GET    /api/v1/analytics/events            → Lista eventos com filtros
         ?camera_id=xxx&plugin_id=xxx&severity=critical&limit=50
```

#### Dashboard
```
GET    /api/v1/analytics/stats             → Estatísticas completas
         ?hours=24
```

### 4. Database Migration (`scripts/analytics_tables.sql`)

SQL pronto para rodar:
```bash
psql -U vms -d vms -f scripts/analytics_tables.sql
```

Cria:
- Tabela `plugin_installations` com índices
- Tabela `analytics_events` com índices e FK

---

## 📊 Fluxo Completo de Uso

### 1. Usuário vê catálogo
```
GET /api/v1/analytics/catalog
→ Retorna 8 plugins disponíveis com metadata
```

### 2. Usuário instala plugin
```
POST /api/v1/analytics/install
{
  "plugin_id": "fire_smoke",
  "edge_agent_id": "edge-001",
  "fps_target": 2
}
→ Registra em plugin_installations
→ (TODO: WebSocket para edge agent baixar modelo)
```

### 3. Edge agent roda detecção
```
Edge agent:
  1. Baixa modelo fire.pt
  2. Carrega com ResourceOptimizer (GPU se disponível)
  3. Processa frames a 2 FPS
  4. Detecta fogo → envia evento:

POST /api/v1/analytics/events
{
  "plugin_id": "fire_smoke",
  "camera_id": "cam-001",
  "camera_name": "Entrada",
  "event_type": "fire_smoke_detected",
  "severity": "critical",
  "confidence": 0.94,
  "payload": {
    "detection_type": "Fire",
    "bbox": [0.3, 0.4, 0.5, 0.6],
    "severity": "critical"
  },
  "occurred_at": "2026-04-11T14:32:10"
}
```

### 4. Dashboard mostra stats
```
GET /api/v1/analytics/stats?hours=24
→ Retorna:
{
  "total": 142,
  "by_severity": {
    "critical": 12,
    "warning": 45,
    "info": 85
  },
  "by_plugin": {
    "fire_smoke": 23,
    "ppe_detection": 67,
    "vehicle_count": 52
  },
  "top_cameras": [
    {"camera_id": "cam-001", "camera_name": "Entrada", "count": 45},
    ...
  ],
  "period_hours": 24
}
```

---

## 🔌 Integração com Frontend

O frontend criado (AnalyticsCatalog.tsx, AnalyticsEvents.tsx) já está configurado para usar estes endpoints.

**Próximos passos no frontend:**
1. Substituir `AVAILABLE_PLUGINS` mock por chamada `GET /api/v1/analytics/catalog`
2. `handleInstall` → `POST /api/v1/analytics/install`
3. `AnalyticsEvents` → `GET /api/v1/analytics/events`
4. Dashboard stats → `GET /api/v1/analytics/stats`

---

## 🚀 Como Rodar

### 1. Criar tabelas no banco
```bash
psql -U vms -d vms -f scripts/analytics_tables.sql
```

### 2. Rebuild da API
```bash
cd D:\so\vms\mvp
docker compose up --build -d api
```

### 3. Testar endpoints
```bash
# Catálogo
curl http://localhost:8000/api/v1/analytics/catalog

# Instalar plugin (com auth)
curl -X POST http://localhost:8000/api/v1/analytics/install \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"plugin_id":"fire_smoke","edge_agent_id":"edge-001"}'

# Stats
curl http://localhost:8000/api/v1/analytics/stats?hours=24 \
  -H "Authorization: Bearer <token>"
```

---

## 📁 Arquivos Criados/Modificados

| Arquivo | Ação | Descrição |
|---------|------|-----------|
| `api/src/vms/analytics/models.py` | ✅ Criado | SQLAlchemy models |
| `api/src/vms/analytics/service.py` | ✅ Criado | Service layer completa |
| `api/src/vms/analytics/router.py` | ✅ Reescrito | 10 endpoints reais |
| `api/src/vms/main.py` | ✅ Modificado | Router analytics registrado |
| `scripts/analytics_tables.sql` | ✅ Criado | Migration SQL |

---

*Backend Analytics completo — 11 de Abril de 2026*
