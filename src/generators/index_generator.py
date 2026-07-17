"""
Generador de página índice para el sitio de reportes de Kiro Analytics.

Produce un documento HTML auto-contenido (index.html) que lista todos los
reportes existentes organizados por secciones de periodo (diario, semanal,
mensual), con el reporte más reciente al inicio de cada sección.
"""
from __future__ import annotations

from typing import List

from src.models import ReportMetadata


# Mapeo de periodos internos a etiquetas en español para la UI
_PERIOD_LABELS = {
    "daily": "Diario",
    "weekly": "Semanal",
    "monthly": "Mensual",
}

# Orden de las secciones en la página índice
_PERIOD_ORDER = ["weekly", "monthly"]


def generate_index(existing_reports: List[ReportMetadata]) -> str:
    """
    Genera una página index.html con todos los reportes organizados por periodo.

    La función recibe únicamente reportes que existen actualmente en el bucket
    (los reportes eliminados por política de ciclo de vida ya están excluidos).

    Cada entrada muestra: tipo de periodo, fechas de cobertura, fecha de
    generación y un enlace directo al reporte HTML.

    El reporte más reciente aparece primero dentro de cada sección, ordenado
    por fecha de inicio descendente.

    Args:
        existing_reports: Lista de metadatos de reportes que existen en el bucket.

    Returns:
        String con el documento HTML completo de la página índice.
    """
    # Agrupar reportes por periodo
    reports_by_period = _group_by_period(existing_reports)

    # Construir el HTML
    html = _build_index_head()
    html += _build_index_body_open()
    html += _build_index_header(len(existing_reports))
    html += _build_index_sections(reports_by_period)
    html += _build_index_footer()

    return html


def _group_by_period(
    reports: List[ReportMetadata],
) -> dict:
    """
    Agrupa los reportes por tipo de periodo y los ordena por fecha de inicio
    descendente (más reciente primero).

    Args:
        reports: Lista de metadatos de reportes.

    Returns:
        Diccionario con claves de periodo y listas de reportes ordenados.
    """
    grouped: dict = {period: [] for period in _PERIOD_ORDER}

    for report in reports:
        period = report.period
        if period in grouped:
            grouped[period].append(report)
        # Ignorar periodos no reconocidos

    # Ordenar cada grupo por start_date descendente (más reciente primero)
    for period in grouped:
        grouped[period].sort(key=lambda r: r.start_date, reverse=True)

    return grouped


def _build_index_head() -> str:
    """Construye el <head> del documento HTML con CSS inline."""
    return """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kiro Analytics - Índice de Reportes</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 0; background: #f0f2f5; color: #333; }
  .container { max-width: 900px; margin: 0 auto; padding: 30px 20px; }
  .header { background: linear-gradient(135deg, #232f3e 0%, #37475a 100%); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }
  .header h1 { margin: 0 0 8px 0; font-size: 1.8em; }
  .header p { color: #ccc; margin: 0; font-size: 0.95em; }
  .section { margin-bottom: 30px; }
  .section h2 { color: #232f3e; font-size: 1.3em; margin: 0 0 12px 0; padding-bottom: 8px; border-bottom: 2px solid #ff9900; }
  .report-list { list-style: none; padding: 0; margin: 0; }
  .report-item { background: white; border-radius: 8px; padding: 16px 20px; margin-bottom: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); display: flex; justify-content: space-between; align-items: center; transition: box-shadow 0.2s; }
  .report-item:hover { box-shadow: 0 3px 8px rgba(0,0,0,0.12); }
  .report-info { flex: 1; }
  .report-period { font-weight: 600; color: #232f3e; font-size: 0.95em; }
  .report-dates { color: #555; font-size: 0.9em; margin-top: 4px; }
  .report-generated { color: #888; font-size: 0.8em; margin-top: 2px; }
  .report-link a { display: inline-block; background: #ff9900; color: white; text-decoration: none; padding: 8px 16px; border-radius: 6px; font-size: 0.85em; font-weight: 600; transition: background 0.2s; }
  .report-link a:hover { background: #e68a00; }
  .empty-section { color: #999; font-style: italic; padding: 12px 0; }
  .badge { display: inline-block; background: #eef1ff; color: #232f3e; font-size: 0.75em; padding: 2px 8px; border-radius: 10px; margin-left: 8px; font-weight: 600; }
  .footer { text-align: center; color: #999; font-size: 0.8em; margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; }
</style>
</head>
"""


def _build_index_body_open() -> str:
    """Abre el body y el contenedor principal."""
    return """<body>
<div class="container">
"""


def _build_index_header(total_reports: int) -> str:
    """
    Construye el encabezado de la página índice.

    Args:
        total_reports: Número total de reportes disponibles.

    Returns:
        HTML del encabezado.
    """
    return f"""<div class="header">
  <h1>&#128202; Kiro Analytics - Reportes</h1>
  <p>{total_reports} reporte{"s" if total_reports != 1 else ""} disponible{"s" if total_reports != 1 else ""}</p>
</div>
"""


def _build_index_sections(reports_by_period: dict) -> str:
    """
    Construye las secciones de reportes organizadas por periodo.

    Args:
        reports_by_period: Diccionario con reportes agrupados por periodo.

    Returns:
        HTML de todas las secciones.
    """
    html = ""
    for period in _PERIOD_ORDER:
        reports = reports_by_period.get(period, [])
        label = _PERIOD_LABELS.get(period, period)
        count = len(reports)

        html += f"""<div class="section">
  <h2>{label} <span class="badge">{count}</span></h2>
"""
        if not reports:
            html += '  <p class="empty-section">No hay reportes disponibles para este periodo.</p>\n'
        else:
            html += '  <ul class="report-list">\n'
            for report in reports:
                html += _build_report_entry(report)
            html += "  </ul>\n"

        html += "</div>\n"

    return html


def _build_report_entry(report: ReportMetadata) -> str:
    """
    Construye una entrada individual de reporte en la lista.

    Args:
        report: Metadatos del reporte.

    Returns:
        HTML de la entrada del reporte.
    """
    period_label = _PERIOD_LABELS.get(report.period, report.period)
    # Formatear fecha de generación para mostrar solo fecha y hora
    generated_display = report.generated_at[:19].replace("T", " ") if report.generated_at else ""

    return f"""    <li class="report-item">
      <div class="report-info">
        <div class="report-period">{_escape(period_label)}</div>
        <div class="report-dates">Cobertura: {_escape(report.start_date)} a {_escape(report.end_date)}</div>
        <div class="report-generated">Generado: {_escape(generated_display)}</div>
      </div>
      <div class="report-link">
        <a href="{_escape(report.filename)}">Ver reporte</a>
      </div>
    </li>
"""


def _build_index_footer() -> str:
    """Cierra el documento HTML."""
    return """</div>
<div class="footer">
  <p>Kiro Analytics &mdash; Generado autom&aacute;ticamente</p>
</div>
</body>
</html>"""


def _escape(text: str) -> str:
    """
    Escapa caracteres HTML especiales para prevenir inyección.

    Args:
        text: Texto a escapar.

    Returns:
        Texto con caracteres HTML especiales escapados.
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def lambda_handler(event: dict, context=None) -> dict:
    """Handler Lambda para Step Functions — actualiza página índice del sitio."""
    import os
    import re

    import boto3

    from src.models import ReportMetadata

    reports_bucket = os.environ["REPORTS_BUCKET"]
    site_prefix = os.environ.get("SITE_PREFIX", "site/")

    s3_client = boto3.client("s3")

    # Listar reportes existentes en el bucket
    existing_reports = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=reports_bucket, Prefix="reports/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".html"):
                filename = key.split("/")[-1]
                # Parsear filename: kiro_report_{period}_{start}_{end}.html
                match = re.match(
                    r"kiro_report_(\w+)_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})",
                    filename,
                )
                if match:
                    existing_reports.append(
                        ReportMetadata(
                            filename=filename,
                            period=match.group(1),
                            start_date=match.group(2),
                            end_date=match.group(3),
                            generated_at=obj["LastModified"].isoformat(),
                            s3_key=key,
                        )
                    )

    # Generar y subir índice
    index_html = generate_index(existing_reports)
    index_key = site_prefix + "index.html"
    s3_client.put_object(
        Bucket=reports_bucket,
        Key=index_key,
        Body=index_html.encode("utf-8"),
        ContentType="text/html",
    )

    # Invalidar cache de CloudFront
    distribution_id = os.environ.get("CLOUDFRONT_DISTRIBUTION_ID", "")
    if distribution_id:
        try:
            cf_client = boto3.client("cloudfront")
            cf_client.create_invalidation(
                DistributionId=distribution_id,
                InvalidationBatch={
                    "Paths": {"Quantity": 1, "Items": ["/*"]},
                    "CallerReference": f"index-update-{existing_reports[0].generated_at if existing_reports else 'empty'}",
                },
            )
        except Exception:
            pass  # Best-effort, no bloquear el pipeline

    return {"index_key": index_key, "reports_count": len(existing_reports)}
