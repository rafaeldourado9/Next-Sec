"""Entidades de domínio de relatórios."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from vms.shared.kernel import ReportId, TenantId


class ReportStatus(StrEnum):
    """Estado de processamento de um relatório."""

    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class ReportType(StrEnum):
    """Tipos de relatórios disponíveis."""

    EVENTS_SUMMARY = "events_summary"
    CAMERAS_STATUS = "cameras_status"
    AUDIT_TRAIL = "audit_trail"
    ANALYTICS_EVENTS = "analytics_events"
    # RECORDINGS_COVERAGE removido — gravação contínua fora do escopo do
    # Next Sec (ver .genesis/architecture/reuse-plan.md)


@dataclass
class Report:
    """
    Relatório gerado pelo sistema.

    Ciclo de vida:
    1. pending: Solicitado pelo usuário
    2. generating: Sendo processado pelo worker
    3. ready: PDF gerado e disponível para download
    4. failed: Erro na geração
    """

    id: ReportId = field(default_factory=lambda: ReportId(uuid4()))
    tenant_id: TenantId | None = None
    report_type: ReportType | None = None
    parameters: dict = field(default_factory=dict)
    status: ReportStatus = ReportStatus.PENDING
    file_path: str | None = None
    sha256_hash: str | None = None
    scheduled_for: datetime | None = None
    generated_at: datetime | None = None
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_ready(self) -> bool:
        return self.status == ReportStatus.READY

    @property
    def is_failed(self) -> bool:
        return self.status == ReportStatus.FAILED

    def start_generation(self) -> None:
        """Marca relatório como sendo gerado."""
        if self.status != ReportStatus.PENDING:
            raise ValueError(f"Não é possível gerar relatório em status '{self.status}'")
        self.status = ReportStatus.GENERATING

    def mark_ready(self, file_path: str, sha256_hash: str) -> None:
        """Marca relatório como pronto."""
        if self.status != ReportStatus.GENERATING:
            raise ValueError(f"Não é possível finalizar relatório em status '{self.status}'")
        self.status = ReportStatus.READY
        self.file_path = file_path
        self.sha256_hash = sha256_hash
        self.generated_at = datetime.utcnow()

    def mark_failed(self) -> None:
        """Marca relatório como falho."""
        self.status = ReportStatus.FAILED
