"""
Tests de propiedad (PBT) para la generación de página índice.

Utiliza Hypothesis para verificar que generate_index produce un documento HTML
con reportes organizados por secciones de periodo, ordenados por fecha
descendente, con información completa en cada entrada.

# Feature: aws-analytics-pipeline, Property 11: Generación de página índice
# Validates: Requirements 8.2
"""
from __future__ import annotations

import re
from typing import List

from hypothesis import given, settings, strategies as st

from src.generators.index_generator import generate_index
from src.models import ReportMetadata


# =============================================================================
# Estrategias (Generators)
# =============================================================================

# Estrategia para periodos válidos reconocidos por el generador de índice
period_strategy = st.sampled_from(["daily", "weekly", "monthly"])

# Estrategia para fechas en formato YYYY-MM-DD
date_strategy = st.dates(
    min_value=__import__("datetime").date(2024, 1, 1),
    max_value=__import__("datetime").date(2026, 12, 31),
).map(lambda d: d.isoformat())

# Estrategia para timestamps ISO 8601
timestamp_strategy = st.builds(
    lambda d, h, m, s: f"{d}T{h:02d}:{m:02d}:{s:02d}",
    d=st.dates(
        min_value=__import__("datetime").date(2024, 1, 1),
        max_value=__import__("datetime").date(2026, 12, 31),
    ).map(lambda d: d.isoformat()),
    h=st.integers(min_value=0, max_value=23),
    m=st.integers(min_value=0, max_value=59),
    s=st.integers(min_value=0, max_value=59),
)


def _build_report_metadata(period: str, start_date: str, end_date: str, generated_at: str) -> ReportMetadata:
    """Construye un ReportMetadata válido a partir de los parámetros dados."""
    filename = f"kiro_report_{period}_{start_date}_{end_date}.html"
    s3_key = f"reports/{filename}"
    return ReportMetadata(
        filename=filename,
        period=period,
        start_date=start_date,
        end_date=end_date,
        generated_at=generated_at,
        s3_key=s3_key,
    )


# Estrategia para generar un ReportMetadata válido
report_metadata_strategy = st.builds(
    _build_report_metadata,
    period=period_strategy,
    start_date=date_strategy,
    end_date=date_strategy,
    generated_at=timestamp_strategy,
)

# Estrategia para listas de reportes (entre 0 y 20 elementos)
report_list_strategy = st.lists(
    report_metadata_strategy,
    min_size=0,
    max_size=20,
)


# =============================================================================
# Mapeo de etiquetas de periodo en español
# =============================================================================

PERIOD_LABELS = {
    "daily": "Diario",
    "weekly": "Semanal",
    "monthly": "Mensual",
}

PERIOD_ORDER = ["daily", "weekly", "monthly"]


# =============================================================================
# Tests de propiedad
# =============================================================================

class TestProperty11GeneracionPaginaIndice:
    """
    Property 11: Generación de página índice.

    For any set of report metadata entries, the generated index.html SHALL
    list all reports organized in separate sections by period type (diario,
    semanal, mensual), with each entry showing period type, coverage dates,
    generation date, and a direct link; and the most recent report SHALL
    appear first within its section.

    # Feature: aws-analytics-pipeline, Property 11: Generación de página índice
    **Validates: Requirements 8.2**
    """

    @given(reports=report_list_strategy)
    @settings(max_examples=100)
    def test_reportes_organizados_en_secciones_por_periodo(
        self,
        reports: List[ReportMetadata],
    ):
        """
        Verifica que todos los reportes se organizan en secciones separadas
        por tipo de periodo (diario, semanal, mensual).

        **Validates: Requirements 8.2**
        """
        html = generate_index(reports)

        # Las tres secciones de periodo siempre deben estar presentes
        for period in PERIOD_ORDER:
            label = PERIOD_LABELS[period]
            assert label in html, (
                f"La sección '{label}' no se encontró en el HTML generado. "
                f"Se esperan las tres secciones: Diario, Semanal, Mensual."
            )

        # Las secciones deben aparecer en el orden correcto: Diario < Semanal < Mensual
        pos_diario = html.index(PERIOD_LABELS["daily"])
        pos_semanal = html.index(PERIOD_LABELS["weekly"])
        pos_mensual = html.index(PERIOD_LABELS["monthly"])
        assert pos_diario < pos_semanal < pos_mensual, (
            "Las secciones no están en el orden correcto. "
            f"Se espera Diario ({pos_diario}) < Semanal ({pos_semanal}) < Mensual ({pos_mensual})"
        )

    @given(reports=st.lists(report_metadata_strategy, min_size=1, max_size=20))
    @settings(max_examples=100)
    def test_cada_entrada_muestra_informacion_requerida(
        self,
        reports: List[ReportMetadata],
    ):
        """
        Verifica que cada entrada de reporte muestra: tipo de periodo,
        fechas de cobertura, fecha de generación y un enlace directo.

        **Validates: Requirements 8.2**
        """
        html = generate_index(reports)

        for report in reports:
            # Tipo de periodo (etiqueta en español)
            period_label = PERIOD_LABELS[report.period]
            assert period_label in html, (
                f"La etiqueta de periodo '{period_label}' no aparece en el HTML. "
                f"Reporte: {report.filename}"
            )

            # Fechas de cobertura (start_date y end_date)
            assert report.start_date in html, (
                f"La fecha de inicio '{report.start_date}' no aparece en el HTML. "
                f"Reporte: {report.filename}"
            )
            assert report.end_date in html, (
                f"La fecha de fin '{report.end_date}' no aparece en el HTML. "
                f"Reporte: {report.filename}"
            )

            # Fecha de generación (formateada sin la T)
            generated_display = report.generated_at[:19].replace("T", " ")
            assert generated_display in html, (
                f"La fecha de generación '{generated_display}' no aparece en el HTML. "
                f"Reporte: {report.filename}"
            )

            # Enlace directo al reporte (href con el filename)
            assert f'href="{report.filename}"' in html, (
                f"El enlace directo al reporte '{report.filename}' no se encontró. "
                f"Se esperaba href=\"{report.filename}\" en el HTML."
            )

    @given(reports=st.lists(report_metadata_strategy, min_size=2, max_size=20))
    @settings(max_examples=100)
    def test_reporte_mas_reciente_primero_en_cada_seccion(
        self,
        reports: List[ReportMetadata],
    ):
        """
        Verifica que el reporte más reciente aparece primero dentro de su
        sección (ordenado por start_date descendente).

        **Validates: Requirements 8.2**
        """
        html = generate_index(reports)

        # Agrupar reportes por periodo
        for period in PERIOD_ORDER:
            period_reports = [r for r in reports if r.period == period]
            if len(period_reports) < 2:
                continue

            # Ordenar por start_date descendente (esperado)
            sorted_reports = sorted(
                period_reports,
                key=lambda r: r.start_date,
                reverse=True,
            )

            # Verificar que en el HTML aparecen en el orden correcto
            # Usamos la posición del filename (enlace directo) como indicador de orden
            positions = []
            for report in sorted_reports:
                href_pattern = f'href="{report.filename}"'
                pos = html.find(href_pattern)
                assert pos >= 0, (
                    f"No se encontró el enlace '{href_pattern}' en el HTML."
                )
                positions.append((report.filename, report.start_date, pos))

            # Verificar que las posiciones están en orden ascendente
            # (el primero en el HTML es el más reciente)
            for i in range(len(positions) - 1):
                assert positions[i][2] <= positions[i + 1][2], (
                    f"Orden incorrecto en sección '{period}': "
                    f"'{positions[i][0]}' (start_date={positions[i][1]}) "
                    f"debería aparecer antes que "
                    f"'{positions[i + 1][0]}' (start_date={positions[i + 1][1]}). "
                    f"Se espera orden descendente por start_date."
                )

    @given(reports=report_list_strategy)
    @settings(max_examples=100)
    def test_conteo_total_de_reportes_coincide(
        self,
        reports: List[ReportMetadata],
    ):
        """
        Verifica que el conteo total de reportes mostrado en el HTML
        coincide con la cantidad de reportes de entrada.

        **Validates: Requirements 8.2**
        """
        html = generate_index(reports)
        total = len(reports)

        # El HTML muestra "N reporte(s) disponible(s)"
        if total == 1:
            assert "1 reporte disponible" in html, (
                f"Se esperaba '1 reporte disponible' en el HTML "
                f"para {total} reporte(s) de entrada."
            )
        else:
            expected_text = f"{total} reportes disponibles"
            assert expected_text in html, (
                f"Se esperaba '{expected_text}' en el HTML "
                f"para {total} reporte(s) de entrada."
            )

    @given(reports=report_list_strategy)
    @settings(max_examples=100)
    def test_html_valido_con_estructura_completa(
        self,
        reports: List[ReportMetadata],
    ):
        """
        Verifica que el HTML generado tiene estructura válida:
        DOCTYPE, html, head, body, etc.

        **Validates: Requirements 8.2**
        """
        html = generate_index(reports)

        # DOCTYPE
        assert "<!DOCTYPE html>" in html, (
            "El HTML no contiene la declaración DOCTYPE."
        )

        # Etiqueta html con lang
        assert '<html lang="es">' in html, (
            "El HTML no contiene la etiqueta <html lang=\"es\">."
        )

        # Head con charset
        assert 'charset="UTF-8"' in html, (
            "El HTML no declara charset UTF-8."
        )

        # Body
        assert "<body>" in html, (
            "El HTML no contiene la etiqueta <body>."
        )
        assert "</body>" in html, (
            "El HTML no contiene la etiqueta de cierre </body>."
        )

        # Cierre de html
        assert "</html>" in html, (
            "El HTML no contiene la etiqueta de cierre </html>."
        )

        # Style inline (auto-contenido)
        assert "<style>" in html, (
            "El HTML no contiene estilos CSS inline."
        )

        # Title
        assert "<title>" in html, (
            "El HTML no contiene la etiqueta <title>."
        )
