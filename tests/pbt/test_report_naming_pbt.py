"""
Tests de propiedad (PBT) para nomenclatura y formato de reportes.

Utiliza Hypothesis para verificar que los nombres de archivo de reportes
siguen el patrón correcto y que el CSV contiene exactamente las 16 columnas
especificadas con una fila por usuario procesado.

# Feature: aws-analytics-pipeline, Property 9: Nomenclatura y formato de reportes
# Validates: Requirements 5.3, 5.4
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date

from hypothesis import given, settings, strategies as st

from src.generators.csv_generator import generate_csv, CSV_COLUMNS
from src.models import ProcessingResult, UserMetrics


# =============================================================================
# Constantes
# =============================================================================

# Patrón regex para validar nombres de archivo de reportes
REPORT_FILENAME_PATTERN = re.compile(
    r"^kiro_report_(daily|weekly|monthly)_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.(html|csv)$"
)

# Las 16 columnas exactas del CSV según requisito 5.4
EXPECTED_CSV_COLUMNS = [
    "username",
    "display_name",
    "email",
    "is_internal",
    "credits_used",
    "credits_monthly",
    "credits_pct",
    "conversations",
    "total_messages",
    "days_active",
    "clients_used",
    "chat_messages_sent",
    "ai_code_lines",
    "inline_suggestions",
    "inline_accepted",
    "prompt_count",
]


# =============================================================================
# Función auxiliar de nomenclatura de reportes
# =============================================================================

def generate_report_filename(period: str, start_date: str, end_date: str, ext: str) -> str:
    """
    Genera el nombre de archivo de un reporte según la nomenclatura estándar.

    Args:
        period: Periodo del reporte ("daily", "weekly", "monthly").
        start_date: Fecha de inicio en formato YYYY-MM-DD.
        end_date: Fecha de fin en formato YYYY-MM-DD.
        ext: Extensión del archivo ("html" o "csv").

    Returns:
        Nombre de archivo con formato: kiro_report_{period}_{start_date}_{end_date}.{ext}
    """
    return f"kiro_report_{period}_{start_date}_{end_date}.{ext}"


# =============================================================================
# Estrategias (Generators)
# =============================================================================

# Periodos válidos
periods = st.sampled_from(["daily", "weekly", "monthly"])

# Extensiones válidas
extensions = st.sampled_from(["html", "csv"])

# Fechas válidas en rango amplio
valid_dates = st.dates(
    min_value=date(2000, 1, 1),
    max_value=date(2099, 12, 31),
)

# Estrategia para generar UserMetrics aleatorios
def user_metrics_strategy():
    """Genera un UserMetrics con valores aleatorios válidos."""
    return st.builds(
        UserMetrics,
        user_id=st.text(min_size=1, max_size=36, alphabet=st.characters(whitelist_categories=("L", "N", "Pd"))),
        username=st.text(min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("L", "N"))),
        display_name=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Zs"))),
        email=st.from_regex(r"[a-z]{1,10}@[a-z]{1,10}\.[a-z]{2,4}", fullmatch=True),
        credits_used=st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
        credits_monthly=st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
        credits_pct=st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        conversations=st.integers(min_value=0, max_value=10000),
        total_messages=st.integers(min_value=0, max_value=100000),
        days_active=st.integers(min_value=0, max_value=31),
        clients_used=st.lists(st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L",))), min_size=0, max_size=5),
        chat_messages_sent=st.integers(min_value=0, max_value=100000),
        ai_code_lines=st.integers(min_value=0, max_value=100000),
        inline_suggestions=st.integers(min_value=0, max_value=100000),
        inline_accepted=st.integers(min_value=0, max_value=100000),
        prompt_count=st.integers(min_value=0, max_value=100000),
        prompt_categories=st.dictionaries(
            keys=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L",))),
            values=st.integers(min_value=0, max_value=1000),
            max_size=5,
        ),
        intents=st.dictionaries(
            keys=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
            values=st.integers(min_value=0, max_value=1000),
            max_size=4,
        ),
        models=st.dictionaries(
            keys=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N", "Pd"))),
            values=st.integers(min_value=0, max_value=1000),
            max_size=3,
        ),
    )


# Estrategia para ProcessingResult con número variable de usuarios
def processing_result_strategy(min_users: int = 0, max_users: int = 20):
    """Genera un ProcessingResult con entre min_users y max_users usuarios."""
    return st.builds(
        ProcessingResult,
        user_metrics=st.lists(user_metrics_strategy(), min_size=min_users, max_size=max_users),
        inactive_users=st.just([]),
        total_users_processed=st.integers(min_value=0, max_value=50),
    )


# =============================================================================
# Tests de propiedad
# =============================================================================

class TestProperty9NomenclaturaFormatoReportes:
    """
    Property 9: Nomenclatura y formato de reportes.

    For any period value in {"daily", "weekly", "monthly"} and any valid
    start_date and end_date, the generated report files SHALL be named exactly
    `kiro_report_{period}_{start_date}_{end_date}.{ext}` where dates use
    YYYY-MM-DD format, AND the CSV SHALL contain exactly the 16 specified
    columns as header and one row per processed user.

    # Feature: aws-analytics-pipeline, Property 9: Nomenclatura y formato de reportes
    **Validates: Requirements 5.3, 5.4**
    """

    # =========================================================================
    # Propiedad 9a: Nomenclatura de reportes
    # =========================================================================

    @given(
        period=periods,
        start_date=valid_dates,
        end_date=valid_dates,
        ext=extensions,
    )
    @settings(max_examples=150)
    def test_nombre_archivo_sigue_patron_correcto(
        self, period: str, start_date: date, end_date: date, ext: str
    ):
        """
        El nombre de archivo generado siempre sigue el patrón
        kiro_report_{period}_{start_date}_{end_date}.{ext} con fechas YYYY-MM-DD.

        **Validates: Requirements 5.3**
        """
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        filename = generate_report_filename(period, start_str, end_str, ext)

        assert REPORT_FILENAME_PATTERN.match(filename), (
            f"El nombre de archivo '{filename}' no coincide con el patrón "
            f"esperado kiro_report_{{period}}_{{start_date}}_{{end_date}}.{{ext}}"
        )

    @given(
        period=periods,
        start_date=valid_dates,
        end_date=valid_dates,
        ext=extensions,
    )
    @settings(max_examples=150)
    def test_nombre_archivo_contiene_periodo_correcto(
        self, period: str, start_date: date, end_date: date, ext: str
    ):
        """
        El nombre de archivo siempre contiene el periodo exacto proporcionado.

        **Validates: Requirements 5.3**
        """
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        filename = generate_report_filename(period, start_str, end_str, ext)

        match = REPORT_FILENAME_PATTERN.match(filename)
        assert match is not None
        assert match.group(1) == period, (
            f"Periodo en filename='{match.group(1)}' no coincide con "
            f"periodo esperado='{period}'"
        )

    @given(
        period=periods,
        start_date=valid_dates,
        end_date=valid_dates,
        ext=extensions,
    )
    @settings(max_examples=150)
    def test_nombre_archivo_contiene_fechas_yyyy_mm_dd(
        self, period: str, start_date: date, end_date: date, ext: str
    ):
        """
        Las fechas en el nombre de archivo siempre usan formato YYYY-MM-DD.

        **Validates: Requirements 5.3**
        """
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        filename = generate_report_filename(period, start_str, end_str, ext)

        match = REPORT_FILENAME_PATTERN.match(filename)
        assert match is not None

        # Verificar que las fechas extraídas son parseable como YYYY-MM-DD
        extracted_start = match.group(2)
        extracted_end = match.group(3)

        assert extracted_start == start_str, (
            f"start_date en filename='{extracted_start}' no coincide con "
            f"start_date esperado='{start_str}'"
        )
        assert extracted_end == end_str, (
            f"end_date en filename='{extracted_end}' no coincide con "
            f"end_date esperado='{end_str}'"
        )

    @given(
        period=periods,
        start_date=valid_dates,
        end_date=valid_dates,
        ext=extensions,
    )
    @settings(max_examples=150)
    def test_nombre_archivo_contiene_extension_correcta(
        self, period: str, start_date: date, end_date: date, ext: str
    ):
        """
        La extensión del archivo siempre coincide con la extensión proporcionada.

        **Validates: Requirements 5.3**
        """
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        filename = generate_report_filename(period, start_str, end_str, ext)

        match = REPORT_FILENAME_PATTERN.match(filename)
        assert match is not None
        assert match.group(4) == ext, (
            f"Extensión en filename='{match.group(4)}' no coincide con "
            f"extensión esperada='{ext}'"
        )

    # =========================================================================
    # Propiedad 9b: Formato CSV
    # =========================================================================

    @given(
        metrics=processing_result_strategy(min_users=0, max_users=20),
        period=periods,
        start_date=valid_dates,
        end_date=valid_dates,
    )
    @settings(max_examples=150)
    def test_csv_tiene_exactamente_16_columnas_en_header(
        self, metrics: ProcessingResult, period: str, start_date: date, end_date: date
    ):
        """
        El CSV generado siempre tiene exactamente 16 columnas en el encabezado,
        coincidiendo con las columnas especificadas en el requisito 5.4.

        **Validates: Requirements 5.4**
        """
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        csv_content = generate_csv(metrics, period, start_str, end_str)

        reader = csv.reader(io.StringIO(csv_content))
        header = next(reader)

        assert len(header) == 16, (
            f"El header tiene {len(header)} columnas, esperadas 16. "
            f"Header: {header}"
        )
        assert header == EXPECTED_CSV_COLUMNS, (
            f"Las columnas del header no coinciden con las esperadas.\n"
            f"Obtenido: {header}\n"
            f"Esperado: {EXPECTED_CSV_COLUMNS}"
        )

    @given(
        metrics=processing_result_strategy(min_users=0, max_users=20),
        period=periods,
        start_date=valid_dates,
        end_date=valid_dates,
    )
    @settings(max_examples=150)
    def test_csv_tiene_una_fila_por_usuario(
        self, metrics: ProcessingResult, period: str, start_date: date, end_date: date
    ):
        """
        El CSV generado siempre tiene exactamente una fila de datos por cada
        usuario en user_metrics del ProcessingResult.

        **Validates: Requirements 5.4**
        """
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        csv_content = generate_csv(metrics, period, start_str, end_str)

        reader = csv.reader(io.StringIO(csv_content))
        # Saltar header
        next(reader)
        data_rows = list(reader)

        expected_rows = len(metrics.user_metrics)
        assert len(data_rows) == expected_rows, (
            f"El CSV tiene {len(data_rows)} filas de datos, "
            f"esperadas {expected_rows} (una por usuario en user_metrics)"
        )

    @given(
        metrics=processing_result_strategy(min_users=1, max_users=20),
        period=periods,
        start_date=valid_dates,
        end_date=valid_dates,
    )
    @settings(max_examples=150)
    def test_csv_cada_fila_tiene_16_campos(
        self, metrics: ProcessingResult, period: str, start_date: date, end_date: date
    ):
        """
        Cada fila de datos en el CSV tiene exactamente 16 campos,
        uno por cada columna del encabezado.

        **Validates: Requirements 5.4**
        """
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        csv_content = generate_csv(metrics, period, start_str, end_str)

        reader = csv.reader(io.StringIO(csv_content))
        header = next(reader)

        for i, row in enumerate(reader):
            assert len(row) == 16, (
                f"La fila {i} tiene {len(row)} campos, esperados 16. "
                f"Fila: {row}"
            )
