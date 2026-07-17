"""
Tests de propiedad (PBT) para la completitud de secciones del reporte HTML.

Utiliza Hypothesis para verificar que el generador HTML produce un documento
con todas las secciones requeridas, independientemente de los datos de entrada.

# Feature: aws-analytics-pipeline, Property 8: Completitud de secciones del reporte HTML
# Validates: Requirements 5.1
"""
from __future__ import annotations

from typing import Dict, List, Optional

from hypothesis import given, settings, strategies as st

from src.generators.html_generator import generate_html
from src.models import AIAnalysisResult, ProcessingResult, User, UserMetrics


# =============================================================================
# Estrategias (Generators)
# =============================================================================

# Estrategia para generar user_ids únicos
user_id_strategy = st.text(
    alphabet=st.sampled_from("abcdef0123456789"),
    min_size=8,
    max_size=16,
).filter(lambda s: len(s) >= 8)

# Estrategia para generar usernames
username_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_"),
    min_size=3,
    max_size=12,
)

# Estrategia para generar display names
display_name_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz AEIOU"),
    min_size=2,
    max_size=20,
).filter(lambda s: s.strip() != "")

# Estrategia para generar emails
email_strategy = st.builds(
    lambda user, domain: f"{user}@{domain}.com",
    user=st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
        min_size=3,
        max_size=8,
    ),
    domain=st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
        min_size=3,
        max_size=6,
    ),
)

# Estrategia para generar clientes usados
clients_strategy = st.lists(
    st.sampled_from(["vscode", "jetbrains", "vim", "web", "cli"]),
    min_size=0,
    max_size=3,
    unique=True,
)

# Estrategia para generar categorías de prompts
prompt_categories_strategy = st.dictionaries(
    keys=st.sampled_from([
        "Código", "Infraestructura", "Base de Datos", "Testing",
        "Documentación", "Refactoring", "Frontend", "Análisis",
        "Configuración", "Otros",
    ]),
    values=st.integers(min_value=0, max_value=50),
    min_size=0,
    max_size=5,
)

# Estrategia para generar intents
intents_strategy = st.dictionaries(
    keys=st.sampled_from(["chat", "do", "spec", "total"]),
    values=st.integers(min_value=0, max_value=100),
    min_size=0,
    max_size=4,
)

# Estrategia para generar modelos
models_strategy = st.dictionaries(
    keys=st.sampled_from(["claude-haiku", "claude-sonnet", "gpt-4"]),
    values=st.integers(min_value=0, max_value=50),
    min_size=0,
    max_size=3,
)

# Estrategia para generar un UserMetrics válido
user_metrics_strategy = st.builds(
    UserMetrics,
    user_id=user_id_strategy,
    username=username_strategy,
    display_name=display_name_strategy,
    email=email_strategy,
    credits_used=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    credits_monthly=st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    credits_pct=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    conversations=st.integers(min_value=0, max_value=200),
    total_messages=st.integers(min_value=0, max_value=1000),
    days_active=st.integers(min_value=0, max_value=31),
    clients_used=clients_strategy,
    chat_messages_sent=st.integers(min_value=0, max_value=500),
    ai_code_lines=st.integers(min_value=0, max_value=5000),
    inline_suggestions=st.integers(min_value=0, max_value=500),
    inline_accepted=st.integers(min_value=0, max_value=500),
    prompt_count=st.integers(min_value=0, max_value=200),
    prompt_categories=prompt_categories_strategy,
    intents=intents_strategy,
    models=models_strategy,
)

# Estrategia para generar un User inactivo
inactive_user_strategy = st.builds(
    User,
    user_id=user_id_strategy,
    username=username_strategy,
    display_name=display_name_strategy,
    email=email_strategy,
    status=st.just("Enabled"),
)

# Estrategia para generar un ProcessingResult válido
processing_result_strategy = st.builds(
    lambda user_metrics, inactive_users: ProcessingResult(
        user_metrics=user_metrics,
        inactive_users=inactive_users,
        total_users_processed=len(user_metrics) + len(inactive_users),
    ),
    user_metrics=st.lists(user_metrics_strategy, min_size=0, max_size=15),
    inactive_users=st.lists(inactive_user_strategy, min_size=0, max_size=10),
)

# Estrategia para generar texto de análisis AI (no vacío)
ai_analysis_text_strategy = st.text(
    alphabet=st.sampled_from(
        "abcdefghijklmnopqrstuvwxyz AEIOU0123456789.,;:-\n"
    ),
    min_size=10,
    max_size=200,
).filter(lambda s: s.strip() != "")

# Estrategia para generar AIAnalysisResult disponible
ai_analysis_available_strategy = st.builds(
    AIAnalysisResult,
    analysis_text=ai_analysis_text_strategy,
    available=st.just(True),
    model_used=st.sampled_from([
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "claude-haiku",
    ]),
    tokens_used=st.integers(min_value=100, max_value=5000),
    duration_seconds=st.floats(min_value=0.1, max_value=60.0, allow_nan=False, allow_infinity=False),
)

# Estrategia para generar AIAnalysisResult no disponible
ai_analysis_unavailable_strategy = st.builds(
    AIAnalysisResult,
    analysis_text=st.just(""),
    available=st.just(False),
    model_used=st.just(""),
    tokens_used=st.just(0),
    duration_seconds=st.just(0.0),
)

# Estrategia para periodos válidos
period_strategy = st.sampled_from(["daily", "weekly", "monthly"])

# Estrategia para fechas en formato YYYY-MM-DD
date_strategy = st.dates(
    min_value=__import__("datetime").date(2024, 1, 1),
    max_value=__import__("datetime").date(2026, 12, 31),
).map(lambda d: d.isoformat())


# =============================================================================
# Secciones requeridas del reporte HTML
# =============================================================================

# IDs de secciones que siempre deben estar presentes
REQUIRED_SECTION_IDS = [
    "kpis",
    "top-usuarios",
    "categorias",
    "detalle",
    "inactivos",
    "ai-analysis",
    "recomendaciones",
]


# =============================================================================
# Tests de propiedad
# =============================================================================

class TestProperty8CompletitudSeccionesHTML:
    """
    Property 8: Completitud de secciones del reporte HTML.

    For any valid set of processed metrics, the generated HTML report SHALL
    contain all required sections: KPIs globales, top 10 usuarios,
    categorización de prompts, tabla detallada por usuario, lista de usuarios
    inactivos, y recomendaciones; and when AI analysis is available, it SHALL
    also contain the análisis AI section.

    # Feature: aws-analytics-pipeline, Property 8: Completitud de secciones del reporte HTML
    **Validates: Requirements 5.1**
    """

    @given(
        metrics=processing_result_strategy,
        ai_analysis=ai_analysis_unavailable_strategy,
        period=period_strategy,
        start_date=date_strategy,
        end_date=date_strategy,
    )
    @settings(max_examples=100)
    def test_todas_las_secciones_presentes_sin_ai(
        self,
        metrics: ProcessingResult,
        ai_analysis: AIAnalysisResult,
        period: str,
        start_date: str,
        end_date: str,
    ):
        """
        Verifica que todas las secciones requeridas están presentes en el HTML
        generado cuando el análisis AI NO está disponible.

        **Validates: Requirements 5.1**
        """
        html = generate_html(metrics, ai_analysis, period, start_date, end_date)

        # Verificar que cada sección requerida tiene su ID presente
        for section_id in REQUIRED_SECTION_IDS:
            assert f'id="{section_id}"' in html, (
                f"Sección '{section_id}' no encontrada en el HTML generado. "
                f"Métricas: {len(metrics.user_metrics)} usuarios, "
                f"{len(metrics.inactive_users)} inactivos, "
                f"periodo={period}, ai_available=False"
            )

    @given(
        metrics=processing_result_strategy,
        ai_analysis=ai_analysis_available_strategy,
        period=period_strategy,
        start_date=date_strategy,
        end_date=date_strategy,
    )
    @settings(max_examples=100)
    def test_todas_las_secciones_presentes_con_ai(
        self,
        metrics: ProcessingResult,
        ai_analysis: AIAnalysisResult,
        period: str,
        start_date: str,
        end_date: str,
    ):
        """
        Verifica que todas las secciones requeridas están presentes en el HTML
        generado cuando el análisis AI SÍ está disponible, y que el texto
        del análisis aparece en la salida.

        **Validates: Requirements 5.1**
        """
        html = generate_html(metrics, ai_analysis, period, start_date, end_date)

        # Verificar que cada sección requerida tiene su ID presente
        for section_id in REQUIRED_SECTION_IDS:
            assert f'id="{section_id}"' in html, (
                f"Sección '{section_id}' no encontrada en el HTML generado. "
                f"Métricas: {len(metrics.user_metrics)} usuarios, "
                f"{len(metrics.inactive_users)} inactivos, "
                f"periodo={period}, ai_available=True"
            )

        # Cuando AI está disponible, el texto del análisis debe aparecer en el HTML
        # El texto se escapa con HTML entities, así que verificamos tokens individuales
        # que no contengan caracteres especiales HTML
        analysis_words = [
            w for w in ai_analysis.analysis_text.split()
            if w and len(w) > 2 and all(c.isalnum() for c in w)
        ]
        if analysis_words:
            # Al menos alguna palabra del análisis debe estar presente
            found_any = any(word in html for word in analysis_words)
            assert found_any, (
                f"El texto del análisis AI no aparece en el HTML generado. "
                f"Texto: '{ai_analysis.analysis_text[:100]}...', "
                f"Palabras buscadas: {analysis_words[:5]}"
            )

    @given(
        metrics=processing_result_strategy,
        period=period_strategy,
        start_date=date_strategy,
        end_date=date_strategy,
    )
    @settings(max_examples=100)
    def test_secciones_presentes_sin_objeto_ai(
        self,
        metrics: ProcessingResult,
        period: str,
        start_date: str,
        end_date: str,
    ):
        """
        Verifica que todas las secciones requeridas están presentes cuando
        ai_analysis es None (no se solicitó análisis AI).

        **Validates: Requirements 5.1**
        """
        html = generate_html(metrics, None, period, start_date, end_date)

        # Verificar que cada sección requerida tiene su ID presente
        for section_id in REQUIRED_SECTION_IDS:
            assert f'id="{section_id}"' in html, (
                f"Sección '{section_id}' no encontrada en el HTML generado "
                f"cuando ai_analysis=None. "
                f"Métricas: {len(metrics.user_metrics)} usuarios, "
                f"{len(metrics.inactive_users)} inactivos, "
                f"periodo={period}"
            )
