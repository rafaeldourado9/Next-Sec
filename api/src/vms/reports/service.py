"""Serviço de geração de relatórios."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from vms.reports.domain import Report, ReportType
from vms.reports.pdf_generator import generate_pdf, render_template
from vms.reports.repository import ReportRepositoryPort
from vms.shared.value_objects import Sha256Hash

logger = logging.getLogger(__name__)


class ReportService:
    """Orquestra a geração de relatórios."""

    def __init__(self, repo: ReportRepositoryPort) -> None:
        self._repo = repo

    async def get_report(self, report_id: str, tenant_id: str) -> Report | None:
        """Retorna relatório por ID."""
        return await self._repo.get_by_id(report_id, tenant_id)

    async def list_reports(
        self,
        tenant_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Report], int]:
        """Lista relatórios do tenant com paginação."""
        offset = (page - 1) * page_size
        return await self._repo.list_by_tenant(tenant_id, limit=page_size, offset=offset)

    async def create_report(
        self,
        tenant_id: str,
        report_type: ReportType,
        parameters: dict,
        user_id: uuid.UUID | None = None,
    ) -> Report:
        """Cria solicitação de relatório."""
        report = Report(
            tenant_id=tenant_id,
            report_type=report_type,
            parameters=parameters,
            created_by=user_id,
        )
        return await self._repo.create(report)

    async def generate_report_pdf(self, report: Report, data: dict, branding: dict | None = None) -> Report:
        """
        Gera o PDF do relatório.

        Args:
            report: Relatório sendo gerado
            data: Dados para o template (extraídos do banco pelo chamador)

        Returns:
            Relatório atualizado com path e hash
        """
        report.start_generation()
        await self._repo.update(report)

        try:
            # Selecionar template
            template_map = {
                ReportType.EVENTS_SUMMARY: "events_report",
                ReportType.CAMERAS_STATUS: "cameras_report",
                ReportType.AUDIT_TRAIL: "audit_trail",
                ReportType.ANALYTICS_EVENTS: "analytics_events",
            }
            template_name = template_map.get(report.report_type, "base")

            # Renderizar HTML
            context = {
                "title": self._get_report_title(report.report_type),
                "params": report.parameters,
                "branding": branding or {},
                **data,
            }
            html = render_template(template_name, context)

            # Gerar PDF
            css_path = os.path.join(os.path.dirname(__file__), "templates", "base.css")
            pdf_bytes = generate_pdf(html, css_path=css_path if os.path.exists(css_path) else None)

            # Salvar em disco
            import tempfile
            output_dir = os.environ.get("REPORTS_PATH", os.path.join(tempfile.gettempdir(), "reports"))
            os.makedirs(output_dir, exist_ok=True)

            filename = f"report_{report.id.value if hasattr(report.id, 'value') else report.id}.pdf"
            file_path = os.path.join(output_dir, filename)

            with open(file_path, "wb") as f:
                f.write(pdf_bytes)

            # Calcular SHA-256
            sha256_hash = Sha256Hash.from_file(file_path).value

            # Finalizar
            report.mark_ready(file_path, sha256_hash)
            await self._repo.update(report)
            logger.info("Relatório gerado com sucesso: %s", file_path)
            return report

        except Exception as exc:
            logger.exception("Falha ao gerar relatório %s", report.id)
            report.mark_failed()
            await self._repo.update(report)
            raise

    def _get_report_title(self, report_type: ReportType | str) -> str:
        titles = {
            ReportType.EVENTS_SUMMARY: "Relatório de Eventos",
            ReportType.CAMERAS_STATUS: "Status de Câmeras",
            ReportType.AUDIT_TRAIL: "Trilha de Auditoria",
            ReportType.ANALYTICS_EVENTS: "Eventos de Analytics",
        }
        return titles.get(report_type, "Relatório VMS")
