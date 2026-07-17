"""
Tests de propiedad (PBT) para la validación de parámetros de entrada del pipeline.

Utiliza Hypothesis para verificar que el validador cumple con las propiedades
de correctitud definidas en el documento de diseño.

# Feature: aws-analytics-pipeline, Property 1: Validación de parámetros de entrada
# Validates: Requirements 1.5, 1.6, 6.6
"""
from __future__ import annotations

import calendar
from datetime import date

from hypothesis import given, settings, strategies as st, assume

from src.validators.input_validator import validate_input, VALID_OUTPUT_FORMATS
from src.models import VALID_PERIODS


# =============================================================================
# Estrategias (Generators)
# =============================================================================

# Estrategia para periodos válidos
valid_periods = st.sampled_from(VALID_PERIODS)

# Estrategia para fechas calendario válidas en formato YYYY-MM-DD
valid_dates = st.dates(
    min_value=date(1900, 1, 1),
    max_value=date(2099, 12, 31),
).map(lambda d: d.strftime("%Y-%m-%d"))

# Estrategia para formatos de salida válidos
valid_output_formats = st.sampled_from(VALID_OUTPUT_FORMATS)

# Estrategia para periodos inválidos (cadenas que no están en VALID_PERIODS)
invalid_periods = st.text(min_size=1, max_size=20).filter(
    lambda s: s not in VALID_PERIODS
)

# Estrategia para fechas con formato incorrecto (no YYYY-MM-DD)
invalid_date_formats = st.one_of(
    # Formato DD-MM-YYYY
    st.dates().map(lambda d: d.strftime("%d-%m-%Y")),
    # Formato MM/DD/YYYY
    st.dates().map(lambda d: d.strftime("%m/%d/%Y")),
    # Cadenas aleatorias que no son fechas
    st.text(min_size=1, max_size=15).filter(
        lambda s: not _es_fecha_valida(s)
    ),
    # Formato parcial (solo año-mes)
    st.dates().map(lambda d: d.strftime("%Y-%m")),
)

# Estrategia para fechas calendario inválidas (formato correcto pero fecha imposible)
invalid_calendar_dates = st.one_of(
    # Febrero 30 o 31 (siempre inválido)
    st.integers(min_value=2000, max_value=2099).flatmap(
        lambda y: st.just(f"{y:04d}-02-30")
    ),
    # Febrero 29 en año no bisiesto
    st.integers(min_value=2000, max_value=2099).filter(
        lambda y: not calendar.isleap(y)
    ).flatmap(
        lambda y: st.just(f"{y:04d}-02-29")
    ),
    # Día 31 en meses de 30 días (abril, junio, septiembre, noviembre)
    st.tuples(
        st.integers(min_value=2000, max_value=2099),
        st.sampled_from([4, 6, 9, 11]),
    ).map(lambda t: f"{t[0]:04d}-{t[1]:02d}-31"),
)

# Estrategia para valores no booleanos de ai_analysis
non_boolean_values = st.one_of(
    st.text(min_size=1, max_size=10),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.just(None),
    st.lists(st.integers(), max_size=3),
)


# =============================================================================
# Funciones auxiliares
# =============================================================================

def _es_fecha_valida(s: str) -> bool:
    """Verifica si una cadena tiene formato YYYY-MM-DD con fecha calendario válida."""
    from datetime import datetime
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


# =============================================================================
# Tests de propiedad
# =============================================================================

class TestProperty1ValidacionEntrada:
    """
    Property 1: Validación de parámetros de entrada.

    For any input parameter object, the validator SHALL accept it if and only if
    the period is one of "daily", "weekly", "monthly" AND the reference_date
    matches the format YYYY-MM-DD with a valid calendar date; otherwise it SHALL
    reject with a descriptive error message indicating the invalid parameter.

    # Feature: aws-analytics-pipeline, Property 1: Validación de parámetros de entrada
    # Validates: Requirements 1.5, 1.6, 6.6
    """

    @given(
        period=valid_periods,
        ref_date=valid_dates,
        ai_analysis=st.booleans(),
        output_format=valid_output_formats,
    )
    @settings(max_examples=150)
    def test_entradas_validas_siempre_producen_valid_true(
        self, period: str, ref_date: str, ai_analysis: bool, output_format: str
    ):
        """
        Entradas válidas (periodo válido + fecha válida + booleano + formato válido)
        siempre producen valid=True con los parámetros correctos normalizados.

        **Validates: Requirements 1.5**
        """
        event = {
            "period": period,
            "reference_date": ref_date,
            "ai_analysis": ai_analysis,
            "output_format": output_format,
        }
        result = validate_input(event)

        assert result.valid is True, f"Debería ser válido: {event}, error: {result.error}"
        assert result.params is not None
        assert result.params.period == period
        assert result.params.reference_date == ref_date
        assert result.params.ai_analysis == ai_analysis
        assert result.params.output_format == output_format
        assert result.error is None

    @given(period=invalid_periods, ref_date=valid_dates)
    @settings(max_examples=150)
    def test_periodo_invalido_siempre_produce_valid_false(
        self, period: str, ref_date: str
    ):
        """
        Un periodo inválido siempre produce valid=False con error que menciona 'period'.

        **Validates: Requirements 1.5, 1.6, 6.6**
        """
        event = {
            "period": period,
            "reference_date": ref_date,
        }
        result = validate_input(event)

        assert result.valid is False, f"Debería ser inválido con period='{period}'"
        assert result.params is None
        assert result.error is not None
        assert "period" in result.error.lower(), (
            f"El error debe mencionar 'period', pero fue: {result.error}"
        )

    @given(period=valid_periods, bad_date=invalid_date_formats)
    @settings(max_examples=150)
    def test_formato_fecha_invalido_siempre_produce_valid_false(
        self, period: str, bad_date: str
    ):
        """
        Un formato de fecha inválido siempre produce valid=False con error
        que menciona 'reference_date'.

        **Validates: Requirements 1.6, 6.6**
        """
        event = {
            "period": period,
            "reference_date": bad_date,
        }
        result = validate_input(event)

        assert result.valid is False, (
            f"Debería ser inválido con reference_date='{bad_date}'"
        )
        assert result.params is None
        assert result.error is not None
        assert "reference_date" in result.error.lower(), (
            f"El error debe mencionar 'reference_date', pero fue: {result.error}"
        )

    @given(period=valid_periods, bad_date=invalid_calendar_dates)
    @settings(max_examples=150)
    def test_fecha_calendario_invalida_siempre_produce_valid_false(
        self, period: str, bad_date: str
    ):
        """
        Fechas calendario inválidas (ej. Feb 30, Feb 29 en año no bisiesto,
        día 31 en meses de 30 días) siempre producen valid=False.

        **Validates: Requirements 1.6, 6.6**
        """
        event = {
            "period": period,
            "reference_date": bad_date,
        }
        result = validate_input(event)

        assert result.valid is False, (
            f"Debería ser inválido con fecha calendario inválida: '{bad_date}'"
        )
        assert result.params is None
        assert result.error is not None
        assert "reference_date" in result.error.lower(), (
            f"El error debe mencionar 'reference_date', pero fue: {result.error}"
        )

    @given(
        period=valid_periods,
        ref_date=valid_dates,
        bad_ai=non_boolean_values,
    )
    @settings(max_examples=150)
    def test_ai_analysis_no_booleano_siempre_produce_valid_false(
        self, period: str, ref_date: str, bad_ai
    ):
        """
        Un valor no booleano para ai_analysis siempre produce valid=False
        con error que menciona 'ai_analysis'.

        **Validates: Requirements 1.5**
        """
        # Excluir True y False ya que son booleanos válidos
        assume(not isinstance(bad_ai, bool))

        event = {
            "period": period,
            "reference_date": ref_date,
            "ai_analysis": bad_ai,
        }
        result = validate_input(event)

        assert result.valid is False, (
            f"Debería ser inválido con ai_analysis={bad_ai!r}"
        )
        assert result.params is None
        assert result.error is not None
        assert "ai_analysis" in result.error.lower(), (
            f"El error debe mencionar 'ai_analysis', pero fue: {result.error}"
        )

    @given(
        period=valid_periods,
        ref_date=valid_dates,
        bad_format=st.text(min_size=1, max_size=20).filter(
            lambda s: s not in VALID_OUTPUT_FORMATS
        ),
    )
    @settings(max_examples=150)
    def test_output_format_invalido_siempre_produce_valid_false(
        self, period: str, ref_date: str, bad_format: str
    ):
        """
        Un output_format inválido siempre produce valid=False con error
        que menciona 'output_format'.

        **Validates: Requirements 1.5**
        """
        event = {
            "period": period,
            "reference_date": ref_date,
            "output_format": bad_format,
        }
        result = validate_input(event)

        assert result.valid is False, (
            f"Debería ser inválido con output_format='{bad_format}'"
        )
        assert result.params is None
        assert result.error is not None
        assert "output_format" in result.error.lower(), (
            f"El error debe mencionar 'output_format', pero fue: {result.error}"
        )
