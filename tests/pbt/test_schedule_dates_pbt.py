"""
Tests de propiedad (PBT) para el cálculo de fechas de ejecuciones programadas.

Utiliza Hypothesis para verificar que el calculador de schedule produce
las fechas de referencia correctas según el tipo de programación.

# Feature: aws-analytics-pipeline, Property 10: Cálculo de fechas para ejecuciones programadas
# Validates: Requirements 6.4
"""
from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given, settings, strategies as st

from src.utils.date_utils import calculate_schedule_params


# =============================================================================
# Estrategias (Generators)
# =============================================================================

# Estrategia para fechas de disparo (trigger_date) en un rango amplio
trigger_dates = st.dates(
    min_value=date(1901, 1, 1),
    max_value=date(2099, 12, 31),
)

# Estrategia para tipos de schedule válidos
schedule_types = st.sampled_from(["daily", "weekly", "monthly"])


# =============================================================================
# Tests de propiedad
# =============================================================================

class TestProperty10CalculoFechasSchedule:
    """
    Property 10: Cálculo de fechas para ejecuciones programadas.

    For any trigger date, the schedule calculator SHALL produce:
    - for daily schedule, reference_date = trigger_date - 1 day;
    - for weekly schedule, reference_date = Monday of the previous week;
    - for monthly schedule, reference_date = first day of the previous month.
    The period parameter SHALL always match the schedule type.

    # Feature: aws-analytics-pipeline, Property 10: Cálculo de fechas para ejecuciones programadas
    **Validates: Requirements 6.4**
    """

    @given(trigger_date=trigger_dates)
    @settings(max_examples=150)
    def test_daily_reference_date_es_dia_anterior(self, trigger_date: date):
        """
        Para schedule diario, reference_date siempre es trigger_date - 1 día.

        **Validates: Requirements 6.4**
        """
        result = calculate_schedule_params("daily", trigger_date)

        expected_date = trigger_date - timedelta(days=1)
        assert result.reference_date == expected_date.isoformat(), (
            f"Para daily con trigger_date={trigger_date}, "
            f"esperado reference_date={expected_date.isoformat()}, "
            f"obtenido={result.reference_date}"
        )

    @given(trigger_date=trigger_dates)
    @settings(max_examples=150)
    def test_weekly_reference_date_es_lunes_semana_anterior(self, trigger_date: date):
        """
        Para schedule semanal, reference_date siempre es el lunes de la semana anterior.

        **Validates: Requirements 6.4**
        """
        result = calculate_schedule_params("weekly", trigger_date)

        # Calcular lunes de la semana actual
        current_monday = trigger_date - timedelta(days=trigger_date.weekday())
        # Lunes de la semana anterior
        previous_monday = current_monday - timedelta(weeks=1)

        assert result.reference_date == previous_monday.isoformat(), (
            f"Para weekly con trigger_date={trigger_date} "
            f"(weekday={trigger_date.weekday()}), "
            f"esperado reference_date={previous_monday.isoformat()}, "
            f"obtenido={result.reference_date}"
        )

    @given(trigger_date=trigger_dates)
    @settings(max_examples=150)
    def test_weekly_reference_date_siempre_es_lunes(self, trigger_date: date):
        """
        Para schedule semanal, reference_date siempre cae en lunes (weekday=0).

        **Validates: Requirements 6.4**
        """
        result = calculate_schedule_params("weekly", trigger_date)

        ref_date = date.fromisoformat(result.reference_date)
        assert ref_date.weekday() == 0, (
            f"Para weekly con trigger_date={trigger_date}, "
            f"reference_date={result.reference_date} no es lunes "
            f"(weekday={ref_date.weekday()})"
        )

    @given(trigger_date=trigger_dates)
    @settings(max_examples=150)
    def test_monthly_reference_date_es_primer_dia_mes_anterior(self, trigger_date: date):
        """
        Para schedule mensual, reference_date siempre es el primer día del mes anterior.

        **Validates: Requirements 6.4**
        """
        result = calculate_schedule_params("monthly", trigger_date)

        # Calcular primer día del mes anterior
        first_of_current = trigger_date.replace(day=1)
        last_of_previous = first_of_current - timedelta(days=1)
        first_of_previous = last_of_previous.replace(day=1)

        assert result.reference_date == first_of_previous.isoformat(), (
            f"Para monthly con trigger_date={trigger_date}, "
            f"esperado reference_date={first_of_previous.isoformat()}, "
            f"obtenido={result.reference_date}"
        )

    @given(trigger_date=trigger_dates)
    @settings(max_examples=150)
    def test_monthly_reference_date_siempre_es_dia_uno(self, trigger_date: date):
        """
        Para schedule mensual, reference_date siempre tiene day=1.

        **Validates: Requirements 6.4**
        """
        result = calculate_schedule_params("monthly", trigger_date)

        ref_date = date.fromisoformat(result.reference_date)
        assert ref_date.day == 1, (
            f"Para monthly con trigger_date={trigger_date}, "
            f"reference_date={result.reference_date} no tiene day=1 "
            f"(day={ref_date.day})"
        )

    @given(schedule_type=schedule_types, trigger_date=trigger_dates)
    @settings(max_examples=150)
    def test_period_siempre_coincide_con_schedule_type(
        self, schedule_type: str, trigger_date: date
    ):
        """
        El campo period del resultado siempre coincide con el schedule_type de entrada.

        **Validates: Requirements 6.4**
        """
        result = calculate_schedule_params(schedule_type, trigger_date)

        assert result.period == schedule_type, (
            f"Para schedule_type='{schedule_type}', "
            f"esperado period='{schedule_type}', "
            f"obtenido period='{result.period}'"
        )

    @given(schedule_type=schedule_types, trigger_date=trigger_dates)
    @settings(max_examples=150)
    def test_reference_date_formato_iso_valido(
        self, schedule_type: str, trigger_date: date
    ):
        """
        El campo reference_date siempre tiene formato YYYY-MM-DD válido.

        **Validates: Requirements 6.4**
        """
        result = calculate_schedule_params(schedule_type, trigger_date)

        # Verificar que se puede parsear como fecha ISO
        try:
            parsed = date.fromisoformat(result.reference_date)
        except (ValueError, TypeError) as e:
            raise AssertionError(
                f"reference_date='{result.reference_date}' no es una fecha "
                f"ISO válida: {e}"
            )

        # Verificar formato exacto YYYY-MM-DD
        assert result.reference_date == parsed.isoformat(), (
            f"reference_date='{result.reference_date}' no tiene formato "
            f"canónico YYYY-MM-DD"
        )
