"""Gerador de PDFs para relatórios (Jinja2 + WeasyPrint)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import jinja2
from weasyprint import HTML

logger = logging.getLogger(__name__)

# Diretório de templates
TEMPLATES_DIR = Path(__file__).parent / "templates"

# Setup Jinja2
jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
    autoescape=True,
)


def render_template(template_name: str, context: dict) -> str:
    """Renderiza template HTML com contexto."""
    template = jinja_env.get_template(f"{template_name}.html")
    return template.render(
        **context,
        generated_at=datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S"),
    )


def generate_pdf(html_content: str, css_path: str | None = None) -> bytes:
    """
    Gera PDF a partir de HTML string usando WeasyPrint.

    Args:
        html_content: HTML completo
        css_path: Caminho opcional para arquivo CSS externo

    Returns:
        Bytes do PDF gerado
    """
    try:
        if css_path:
            from weasyprint import CSS
            pdf_bytes = HTML(string=html_content).write_pdf(
                stylesheets=[CSS(filename=css_path)]
            )
        else:
            pdf_bytes = HTML(string=html_content).write_pdf()
        return pdf_bytes
    except Exception as exc:
        logger.exception("Falha ao gerar PDF com WeasyPrint: %s", exc)
        raise
