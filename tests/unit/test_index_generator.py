"""
Tests unitarios para el generador de página índice.

Verifica que generate_index produce HTML correcto con reportes organizados
por secciones de periodo, ordenados por fecha descendente, y con la
información requerida en cada entrada.
"""
from src.generators.index_generator import generate_index
from src.models import ReportMetadata


def _make_report(
    period: str = "weekly",
    start_date: str = "2026-01-01",
    end_date: str = "2026-01-01",
    generated_at: str = "2026-01-02T07:00:00",
) -> ReportMetadata:
    """Helper para crear un ReportMetadata de prueba."""
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


class TestGenerateIndexEmpty:
    """Tests con lista vacía de reportes."""

    def test_empty_list_returns_valid_html(self):
        """Una lista vacía produce HTML válido con estructura completa."""
        result = generate_index([])
        assert "<!DOCTYPE html>" in result
        assert "</html>" in result

    def test_empty_list_shows_zero_reports(self):
        """Una lista vacía muestra 0 reportes disponibles."""
        result = generate_index([])
        assert "0 reportes disponibles" in result

    def test_empty_list_shows_all_sections(self):
        """Una lista vacía muestra las secciones de periodo semanal y mensual."""
        result = generate_index([])
        assert "Semanal" in result
        assert "Mensual" in result
        assert "Diario" not in result

    def test_empty_list_shows_empty_messages(self):
        """Una lista vacía muestra mensajes de sección vacía."""
        result = generate_index([])
        assert "No hay reportes disponibles para este periodo." in result


class TestGenerateIndexSingleReport:
    """Tests con un solo reporte."""

    def test_single_daily_report(self):
        """Un reporte diario aparece en la sección correcta."""
        report = _make_report(
            period="weekly",
            start_date="2026-06-15",
            end_date="2026-06-15",
            generated_at="2026-06-16T07:00:00",
        )
        result = generate_index([report])
        assert "1 reporte disponible" in result
        assert "2026-06-15" in result
        assert "kiro_report_weekly_2026-06-15_2026-06-15.html" in result

    def test_report_shows_period_label(self):
        """El reporte muestra la etiqueta de periodo en español."""
        report = _make_report(period="weekly")
        result = generate_index([report])
        # La etiqueta "Semanal" aparece tanto en la sección como en la entrada
        assert "Semanal" in result

    def test_report_shows_coverage_dates(self):
        """El reporte muestra las fechas de cobertura."""
        report = _make_report(start_date="2026-06-09", end_date="2026-06-15")
        result = generate_index([report])
        assert "2026-06-09" in result
        assert "2026-06-15" in result

    def test_report_shows_generation_date(self):
        """El reporte muestra la fecha de generación."""
        report = _make_report(generated_at="2026-06-16T07:30:00")
        result = generate_index([report])
        assert "2026-06-16 07:30:00" in result

    def test_report_has_direct_link(self):
        """El reporte tiene un enlace directo al archivo HTML."""
        report = _make_report(
            period="monthly",
            start_date="2026-06-01",
            end_date="2026-06-30",
        )
        result = generate_index([report])
        assert 'href="kiro_report_monthly_2026-06-01_2026-06-30.html"' in result


class TestGenerateIndexMultipleReports:
    """Tests con múltiples reportes."""

    def test_reports_grouped_by_period(self):
        """Los reportes se agrupan correctamente por periodo."""
        reports = [
            _make_report(period="weekly", start_date="2026-06-15"),
            _make_report(period="weekly", start_date="2026-06-09"),
            _make_report(period="monthly", start_date="2026-06-01"),
        ]
        result = generate_index(reports)
        assert "3 reportes disponibles" in result

    def test_most_recent_first_within_section(self):
        """El reporte más reciente aparece primero dentro de su sección."""
        reports = [
            _make_report(period="weekly", start_date="2026-06-10", end_date="2026-06-10"),
            _make_report(period="weekly", start_date="2026-06-15", end_date="2026-06-15"),
            _make_report(period="weekly", start_date="2026-06-12", end_date="2026-06-12"),
        ]
        result = generate_index(reports)
        # El reporte del 15 debe aparecer antes que el del 12, y este antes que el del 10
        pos_15 = result.index("2026-06-15")
        pos_12 = result.index("2026-06-12")
        pos_10 = result.index("2026-06-10")
        assert pos_15 < pos_12 < pos_10

    def test_sections_appear_in_order(self):
        """Las secciones aparecen en orden: Semanal, Mensual."""
        reports = [
            _make_report(period="monthly", start_date="2026-06-01"),
            _make_report(period="weekly", start_date="2026-06-15"),
            _make_report(period="weekly", start_date="2026-06-09"),
        ]
        result = generate_index(reports)
        pos_semanal = result.index("Semanal")
        pos_mensual = result.index("Mensual")
        assert pos_semanal < pos_mensual

    def test_count_badge_per_section(self):
        """Cada sección muestra el conteo correcto de reportes."""
        reports = [
            _make_report(period="weekly", start_date="2026-06-14"),
            _make_report(period="weekly", start_date="2026-06-15"),
            _make_report(period="monthly", start_date="2026-06-01"),
        ]
        result = generate_index(reports)
        # Semanal tiene 2, mensual 1
        assert '<span class="badge">2</span>' in result
        assert '<span class="badge">1</span>' in result


class TestGenerateIndexHTMLStructure:
    """Tests de estructura HTML."""

    def test_html_is_self_contained(self):
        """El HTML es auto-contenido con CSS inline."""
        result = generate_index([])
        assert "<style>" in result
        assert "</style>" in result
        # No debe tener enlaces a CSS externos
        assert 'rel="stylesheet"' not in result

    def test_html_has_proper_lang(self):
        """El HTML tiene el atributo lang correcto."""
        result = generate_index([])
        assert 'lang="es"' in result

    def test_html_has_utf8_charset(self):
        """El HTML declara charset UTF-8."""
        result = generate_index([])
        assert 'charset="UTF-8"' in result

    def test_html_has_title(self):
        """El HTML tiene un título descriptivo."""
        result = generate_index([])
        assert "<title>" in result
        assert "Kiro Analytics" in result


class TestGenerateIndexEdgeCases:
    """Tests de casos borde."""

    def test_unknown_period_ignored(self):
        """Reportes con periodo desconocido se ignoran sin error."""
        report = ReportMetadata(
            filename="unknown.html",
            period="quarterly",
            start_date="2026-01-01",
            end_date="2026-03-31",
            generated_at="2026-04-01T07:00:00",
            s3_key="reports/unknown.html",
        )
        result = generate_index([report])
        # No debe fallar y debe mostrar 0 en todas las secciones
        assert "<!DOCTYPE html>" in result
        assert "</html>" in result

    def test_special_characters_escaped(self):
        """Caracteres especiales en los datos se escapan correctamente."""
        report = ReportMetadata(
            filename='report_<script>alert("xss")</script>.html',
            period="weekly",
            start_date="2026-06-15",
            end_date="2026-06-15",
            generated_at="2026-06-16T07:00:00",
            s3_key="reports/report.html",
        )
        result = generate_index([report])
        assert "<script>" not in result
        assert "&lt;script&gt;" in result
