"""
Tests de propiedad (PBT) para la estructura del resumen de ejecución.

Utiliza Hypothesis para verificar que build_execution_summary() siempre
genera un diccionario con los 8 campos requeridos y tipos correctos,
independientemente del resultado de ejecución (éxito o fallo).

# Feature: aws-analytics-pipeline, Property 13: Estructura del resumen de ejecución

**Validates: Requirements 11.5**
"""
from __future__ import annotations

import re
from datetime import datetime

from hypothesis import given, settings, strategies as st

from src.models import ExecutionResult
from src.utils.execution_summary import build_execution_summary


# =============================================================================
# Estrategias (Generators)
# =============================================================================

# Estrategia para periodos válidos
_periods = st.sampled_from(["daily", "weekly", "monthly"])

# Estrategia para fechas de referencia en formato YYYY-MM-DD
_reference_dates = st.dates(
    min_value=datetime(2020, 1, 1).date(),
    max_value=datetime(2030, 12, 31).date(),
).map(lambda d: d.isoformat())

# Estrategia para estados de ejecución
_statuses = st.sampled_from(["SUCCEEDED", "FAILED"])

# Estrategia para duraciones (float >= 0)
_durations = st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False)

# Estrategia para nombres de etapas
_stage_names = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz_"),
    min_size=3,
    max_size=20,
)

# Estrategia para duraciones por etapa (diccionario con claves string y valores numéricos)
_stage_durations = st.dictionaries(
    keys=_stage_names,
    values=_durations,
    min_size=0,
    max_size=6,
)

# Estrategia para usuarios procesados (entero >= 0)
_users_processed = st.integers(min_value=0, max_value=10000)

# Estrategia para tamaño de datos en bytes
_data_size = st.integers(min_value=0, max_value=100_000_000)

# Estrategia para etapa de fallo (string o None)
_failure_stage = st.one_of(st.none(), _stage_names)

# Estrategia para mensaje de fallo (string o None)
_failure_message = st.one_of(
    st.none(),
    st.text(min_size=1, max_size=100),
)

# Estrategia para execution_id
_execution_ids = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-"),
    min_size=8,
    max_size=36,
)

# Estrategia para timestamps ISO 8601 válidos
_timestamps = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
).map(lambda dt: dt.isoformat())


@st.composite
def execution_results(draw):
    """Estrategia compuesta para generar instancias de ExecutionResult."""
    status = draw(_statuses)
    failure_stage = draw(_failure_stage) if status == "FAILED" else None
    failure_message = draw(_failure_message) if status == "FAILED" else None

    return ExecutionResult(
        execution_id=draw(_execution_ids),
        period=draw(_periods),
        reference_date=draw(_reference_dates),
        status=status,
        total_duration_seconds=draw(_durations),
        stage_durations=draw(_stage_durations),
        users_processed=draw(_users_processed),
        data_size_bytes=draw(_data_size),
        failure_stage=failure_stage,
        failure_message=failure_message,
        report_urls=None,
        timestamp=draw(_timestamps),
    )


# Patrón regex para formato YYYY-MM-DD
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Campos requeridos en el resumen
_REQUIRED_FIELDS = {
    "periodo",
    "fecha_referencia",
    "estado",
    "duracion_total",
    "duracion_por_etapa",
    "usuarios_procesados",
    "etapa_fallo",
    "timestamp",
}


# =============================================================================
# Tests de propiedad
# =============================================================================

class TestProperty13EstructuraResumenEjecucion:
    """
    Property 13: Estructura del resumen de ejecución.

    Para cualquier resultado de ejecución (éxito o fallo), el resumen JSON
    generado DEBE contener todos los campos requeridos con los tipos correctos.

    # Feature: aws-analytics-pipeline, Property 13: Estructura del resumen de ejecución
    **Validates: Requirements 11.5**
    """

    @given(execution_result=execution_results())
    @settings(max_examples=150)
    def test_resumen_contiene_exactamente_8_campos_requeridos(
        self, execution_result: ExecutionResult
    ):
        """
        El resumen siempre contiene exactamente los 8 campos requeridos.

        **Validates: Requirements 11.5**
        """
        summary = build_execution_summary(execution_result)

        assert set(summary.keys()) == _REQUIRED_FIELDS, (
            f"Campos esperados: {_REQUIRED_FIELDS}, "
            f"campos obtenidos: {set(summary.keys())}"
        )

    @given(execution_result=execution_results())
    @settings(max_examples=150)
    def test_periodo_es_string(self, execution_result: ExecutionResult):
        """
        El campo 'periodo' siempre es de tipo string.

        **Validates: Requirements 11.5**
        """
        summary = build_execution_summary(execution_result)

        assert isinstance(summary["periodo"], str), (
            f"'periodo' debería ser str, obtuvo {type(summary['periodo'])}"
        )

    @given(execution_result=execution_results())
    @settings(max_examples=150)
    def test_fecha_referencia_formato_yyyy_mm_dd(
        self, execution_result: ExecutionResult
    ):
        """
        El campo 'fecha_referencia' siempre es string con formato YYYY-MM-DD.

        **Validates: Requirements 11.5**
        """
        summary = build_execution_summary(execution_result)

        assert isinstance(summary["fecha_referencia"], str), (
            f"'fecha_referencia' debería ser str, "
            f"obtuvo {type(summary['fecha_referencia'])}"
        )
        assert _DATE_PATTERN.match(summary["fecha_referencia"]), (
            f"'fecha_referencia' debería tener formato YYYY-MM-DD, "
            f"obtuvo '{summary['fecha_referencia']}'"
        )

    @given(execution_result=execution_results())
    @settings(max_examples=150)
    def test_estado_es_string(self, execution_result: ExecutionResult):
        """
        El campo 'estado' siempre es de tipo string.

        **Validates: Requirements 11.5**
        """
        summary = build_execution_summary(execution_result)

        assert isinstance(summary["estado"], str), (
            f"'estado' debería ser str, obtuvo {type(summary['estado'])}"
        )

    @given(execution_result=execution_results())
    @settings(max_examples=150)
    def test_duracion_total_es_numero_no_negativo(
        self, execution_result: ExecutionResult
    ):
        """
        El campo 'duracion_total' siempre es float >= 0.

        **Validates: Requirements 11.5**
        """
        summary = build_execution_summary(execution_result)

        assert isinstance(summary["duracion_total"], (int, float)), (
            f"'duracion_total' debería ser numérico, "
            f"obtuvo {type(summary['duracion_total'])}"
        )
        assert summary["duracion_total"] >= 0, (
            f"'duracion_total' debería ser >= 0, "
            f"obtuvo {summary['duracion_total']}"
        )

    @given(execution_result=execution_results())
    @settings(max_examples=150)
    def test_duracion_por_etapa_es_dict_con_claves_str_y_valores_numericos(
        self, execution_result: ExecutionResult
    ):
        """
        El campo 'duracion_por_etapa' siempre es dict con claves string
        y valores numéricos.

        **Validates: Requirements 11.5**
        """
        summary = build_execution_summary(execution_result)

        duracion = summary["duracion_por_etapa"]
        assert isinstance(duracion, dict), (
            f"'duracion_por_etapa' debería ser dict, obtuvo {type(duracion)}"
        )
        for key, value in duracion.items():
            assert isinstance(key, str), (
                f"Clave de 'duracion_por_etapa' debería ser str, "
                f"obtuvo {type(key)} para clave '{key}'"
            )
            assert isinstance(value, (int, float)), (
                f"Valor de 'duracion_por_etapa[{key}]' debería ser numérico, "
                f"obtuvo {type(value)}"
            )

    @given(execution_result=execution_results())
    @settings(max_examples=150)
    def test_usuarios_procesados_es_entero_no_negativo(
        self, execution_result: ExecutionResult
    ):
        """
        El campo 'usuarios_procesados' siempre es entero >= 0.

        **Validates: Requirements 11.5**
        """
        summary = build_execution_summary(execution_result)

        assert isinstance(summary["usuarios_procesados"], int), (
            f"'usuarios_procesados' debería ser int, "
            f"obtuvo {type(summary['usuarios_procesados'])}"
        )
        assert summary["usuarios_procesados"] >= 0, (
            f"'usuarios_procesados' debería ser >= 0, "
            f"obtuvo {summary['usuarios_procesados']}"
        )

    @given(execution_result=execution_results())
    @settings(max_examples=150)
    def test_etapa_fallo_es_string_o_none(
        self, execution_result: ExecutionResult
    ):
        """
        El campo 'etapa_fallo' siempre es string o None.

        **Validates: Requirements 11.5**
        """
        summary = build_execution_summary(execution_result)

        etapa = summary["etapa_fallo"]
        assert etapa is None or isinstance(etapa, str), (
            f"'etapa_fallo' debería ser str o None, obtuvo {type(etapa)}"
        )

    @given(execution_result=execution_results())
    @settings(max_examples=150)
    def test_timestamp_es_iso_8601_parseable(
        self, execution_result: ExecutionResult
    ):
        """
        El campo 'timestamp' siempre es un string ISO 8601 parseable
        por datetime.fromisoformat().

        **Validates: Requirements 11.5**
        """
        summary = build_execution_summary(execution_result)

        timestamp = summary["timestamp"]
        assert isinstance(timestamp, str), (
            f"'timestamp' debería ser str, obtuvo {type(timestamp)}"
        )
        try:
            datetime.fromisoformat(timestamp)
        except (ValueError, TypeError) as e:
            raise AssertionError(
                f"'timestamp' debería ser ISO 8601 válido, "
                f"obtuvo '{timestamp}': {e}"
            )
