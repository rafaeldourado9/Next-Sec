"""Schemas Pydantic para relatórios."""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from vms.reports.domain import ReportType


class CreateReportRequest(BaseModel):
    """Solicitação de geração de relatório."""

    report_type: ReportType
    parameters: dict = Field(default_factory=dict)
    # Exemplo: {"from": "2026-01-01", "to": "2026-01-31", "camera_id": "..."}


class ReportResponse(BaseModel):
    """Resposta com dados do relatório."""

    id: str
    tenant_id: str
    report_type: str
    parameters: dict
    status: str
    file_path: str | None = None
    sha256_hash: str | None = None
    generated_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def model_validate(cls, obj, **kwargs):
        # Converte EntityId e UUID para str antes de validar
        if hasattr(obj, '__dataclass_fields__') or hasattr(obj, '__dict__'):
            data = {}
            for field in ('id', 'tenant_id', 'report_type', 'parameters', 'status',
                          'file_path', 'sha256_hash', 'generated_at', 'created_at'):
                val = getattr(obj, field, None)
                if hasattr(val, 'value'):  # EntityId
                    val = str(val.value)
                elif hasattr(val, 'hex'):  # UUID
                    val = str(val)
                data[field] = val
            return cls(**{k: v for k, v in data.items() if v is not None or k in ('file_path', 'sha256_hash', 'generated_at')})
        return super().model_validate(obj, **kwargs)


class ReportListResponse(BaseModel):
    """Lista paginada de relatórios."""

    items: list[ReportResponse]
    total: int
    page: int
    page_size: int

    @classmethod
    def build(cls, items: list, total: int, page: int, page_size: int) -> "ReportListResponse":
        return cls(
            items=[ReportResponse.model_validate(i) for i in items],
            total=total,
            page=page,
            page_size=page_size,
        )
