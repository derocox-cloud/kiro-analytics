"""
Tests unitarios para el generador de reportes HTML.
"""
import pytest

from src.generators.html_generator import generate_html
from src.models import AIAnalysisResult, ProcessingResult, User, UserMetrics


def _make_user_metrics(
    username: str = "testuser",
    display_name: str = "Test User",
    credits_used: float = 50.0,
    credits_monthly: float = 100.0,
    credits_pct: float = 10.0,
    conversations: int = 5,
    total_messages: int = 20,
    days_active: int = 3,
    prompt_count: int = 10,
    prompt_categories: dict = None,
) -> UserMetrics:
    """Helper para crear UserMetrics de prueba."""
    return UserMetrics(
        user_id="uid-001",
        username=username,
        display_name=display_name,
        email=f"{username}@test.com",
        credits_used=credits_used,
        credits_monthly=credits_monthly,
        credits_pct=credits_pct,
        conversations=conversations,
        total_messages=total_messages,
        days_active=days_active,
        clients_used=["VSCode"],
        chat_messages_sent=15,
        ai_code_lines=100,
        inline_suggestions=20,
        inline_accepted=10,
        prompt_count=prompt_count,
        prompt_categories=prompt_categories or {"Código": 5, "Testing": 3},
        intents={"chat": 3, "do": 5, "spec": 2, "total": 10},
        models={"Claude Sonnet 4": 10},
    )


def _make_processing_result(num_users: int = 3) -> ProcessingResult:
    """Helper para crear ProcessingResult de prueba."""
    users = [
        _make_user_metrics(
            username=f"user{i}",
            display_name=f"User {i}",
            credits_used=100.0 - i * 10,
            credits_monthly=200.0 - i * 20,
            credits_pct=(200.0 - i * 20) / 10,
        )
        for i in range(num_users)
    ]
    inactive = [
        User(
            user_id="uid-inactive",
            username="inactive_user",
            display_name="Inactive User",
            email="inactive@test.com",
            status="Enabled",
        )
    ]
    return ProcessingResult(
        user_metrics=users,
        inactive_users=inactive,
        total_users_processed=num_users + 1,
    )


class TestGenerateHtml:
    """Tests para la función generate_html."""

    def test_returns_valid_html_document(self):
        """Verifica que retorna un documento HTML completo."""
        metrics = _make_processing_result()
        result = generate_html(metrics, None, "weekly", "2026-01-05", "2026-01-11")

        assert result.startswith("<!DOCTYPE html>")
        assert "</html>" in result
        assert "<html lang=\"es\">" in result

    def test_contains_all_required_sections(self):
        """Verifica que contiene todas las secciones requeridas (Req 5.1)."""
        metrics = _make_processing_result()
        result = generate_html(metrics, None, "weekly", "2026-01-05", "2026-01-11")

        # KPIs globales
        assert 'id="kpis"' in result
        # Top 10 usuarios
        assert 'id="top-usuarios"' in result
        # Categorización de prompts
        assert 'id="categorias"' in result
        # Tabla detallada por usuario
        assert 'id="detalle"' in result
        # Usuarios inactivos
        assert 'id="inactivos"' in result
        # Análisis AI
        assert 'id="ai-analysis"' in result
        # Recomendaciones
        assert 'id="recomendaciones"' in result

    def test_contains_sidebar_navigation(self):
        """Verifica navegación lateral con enlaces a secciones (Req 5.2)."""
        metrics = _make_processing_result()
        result = generate_html(metrics, None, "weekly", "2026-01-05", "2026-01-11")

        assert '<nav class="sidebar">' in result
        assert 'href="#kpis"' in result
        assert 'href="#top-usuarios"' in result
        assert 'href="#categorias"' in result
        assert 'href="#detalle"' in result
        assert 'href="#inactivos"' in result
        assert 'href="#ai-analysis"' in result
        assert 'href="#recomendaciones"' in result

    def test_contains_inline_css(self):
        """Verifica que incluye CSS inline (Req 5.2)."""
        metrics = _make_processing_result()
        result = generate_html(metrics, None, "daily", "2026-01-05", "2026-01-05")

        assert "<style>" in result
        assert "</style>" in result
        assert ".bar-chart" in result
        assert ".bar-fill" in result

    def test_contains_embedded_javascript(self):
        """Verifica JavaScript embebido para ordenamiento (Req 5.2)."""
        metrics = _make_processing_result()
        result = generate_html(metrics, None, "daily", "2026-01-05", "2026-01-05")

        assert "<script>" in result
        assert "sortTable" in result
        assert 'class="sortable"' in result

    def test_no_external_dependencies(self):
        """Verifica que no hay dependencias externas (Req 5.2)."""
        metrics = _make_processing_result()
        result = generate_html(metrics, None, "daily", "2026-01-05", "2026-01-05")

        # No CDN links
        assert "cdn." not in result.lower()
        assert "https://" not in result
        assert "http://" not in result
        # No external stylesheet links
        assert '<link rel="stylesheet"' not in result

    def test_self_contained_html(self):
        """Verifica que el HTML es auto-contenido."""
        metrics = _make_processing_result()
        result = generate_html(metrics, None, "monthly", "2026-01-01", "2026-01-31")

        # Tiene head y body completos
        assert "<head>" in result
        assert "</head>" in result
        assert "<body>" in result
        assert "</body>" in result

    def test_kpis_show_correct_values(self):
        """Verifica que los KPIs muestran valores correctos."""
        metrics = _make_processing_result(num_users=3)
        result = generate_html(metrics, None, "weekly", "2026-01-05", "2026-01-11")

        # Usuarios activos / total
        assert "3" in result  # active users
        assert "/4" in result  # total registered (3 active + 1 inactive)

    def test_ai_analysis_shown_when_available(self):
        """Verifica que el análisis AI se muestra cuando está disponible."""
        metrics = _make_processing_result()
        ai = AIAnalysisResult(
            analysis_text="## Resumen\nEl equipo muestra buen uso.",
            available=True,
            model_used="claude-haiku-4.5",
            tokens_used=500,
            duration_seconds=2.0,
        )
        result = generate_html(metrics, ai, "weekly", "2026-01-05", "2026-01-11")

        assert "Resumen" in result
        assert "El equipo muestra buen uso" in result
        assert "claude-haiku-4.5" in result

    def test_ai_analysis_not_available_message(self):
        """Verifica mensaje cuando AI no está disponible."""
        metrics = _make_processing_result()
        ai = AIAnalysisResult(
            analysis_text="",
            available=False,
            model_used="",
            tokens_used=0,
            duration_seconds=0.0,
        )
        result = generate_html(metrics, ai, "weekly", "2026-01-05", "2026-01-11")

        assert "no disponible" in result

    def test_inactive_users_listed(self):
        """Verifica que los usuarios inactivos se listan."""
        metrics = _make_processing_result()
        result = generate_html(metrics, None, "weekly", "2026-01-05", "2026-01-11")

        assert "Inactive User" in result
        assert "inactive_user" in result

    def test_top10_bar_chart(self):
        """Verifica que se genera el gráfico de barras CSS para top 10."""
        metrics = _make_processing_result(num_users=12)
        result = generate_html(metrics, None, "weekly", "2026-01-05", "2026-01-11")

        assert "bar-chart" in result
        assert "bar-fill" in result

    def test_spanish_labels(self):
        """Verifica que las etiquetas están en español."""
        metrics = _make_processing_result()
        result = generate_html(metrics, None, "weekly", "2026-01-05", "2026-01-11")

        assert "Usuarios Activos" in result or "Usuarios" in result
        assert "Recomendaciones" in result

    def test_period_displayed_in_header(self):
        """Verifica que el periodo se muestra en el encabezado."""
        metrics = _make_processing_result()
        result = generate_html(metrics, None, "monthly", "2026-01-01", "2026-01-31")

        assert "MONTHLY" in result
        assert "2026-01-01" in result
        assert "2026-01-31" in result
