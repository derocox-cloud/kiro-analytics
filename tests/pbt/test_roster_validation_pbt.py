"""
Tests de propiedad (PBT) para la validación del roster CSV.

Utiliza Hypothesis para verificar que el validador de roster cumple con
las propiedades de correctitud definidas en el documento de diseño.

# Feature: aws-analytics-pipeline, Property 12: Validación de roster CSV

**Validates: Requirements 10.2, 10.3**
"""
import string

from hypothesis import given, settings, strategies as st

from src.models import RosterValidationResult
from src.validators.roster_validator import REQUIRED_COLUMNS, validate_roster


# =============================================================================
# Estrategias (generadores) para datos de prueba
# =============================================================================

# Caracteres seguros para campos CSV (sin comas, saltos de línea ni comillas)
_safe_chars = st.sampled_from(
    string.ascii_letters + string.digits + " _-."
)

# Estrategia para generar un valor de campo CSV seguro (no vacío)
_csv_field = st.text(
    alphabet=_safe_chars, min_size=1, max_size=30
).filter(lambda s: s.strip() != "")

# Estrategia para generar un email simple válido
_email = st.builds(
    lambda user, domain: f"{user}@{domain}.com",
    user=st.text(alphabet=string.ascii_lowercase, min_size=3, max_size=10),
    domain=st.text(alphabet=string.ascii_lowercase, min_size=3, max_size=8),
)

# Estrategia para generar un user_id tipo UUID simplificado
_user_id = st.text(
    alphabet=string.ascii_lowercase + string.digits + "-",
    min_size=8,
    max_size=36,
).filter(lambda s: s.strip() != "" and not s.startswith("-"))

# Estrategia para generar un status válido
_status = st.sampled_from(["Enabled", "Disabled", "Suspended", "Pending"])


def _build_csv_row(username: str, display_name: str, status: str,
                   email: str, user_id: str, columns: list) -> str:
    """Construye una fila CSV respetando el orden de columnas dado."""
    field_map = {
        "Username": username,
        "Display name": display_name,
        "Status": status,
        "Email": email,
        "User ID": user_id,
    }
    return ",".join(field_map[col] for col in columns)


# Estrategia para generar una fila de datos válida (como tupla de campos)
_valid_row = st.tuples(_csv_field, _csv_field, _status, _email, _user_id)


def _build_valid_csv(rows: list, columns: list = None) -> str:
    """
    Construye un CSV válido con encabezado y filas de datos.

    Args:
        rows: Lista de tuplas (username, display_name, status, email, user_id)
        columns: Orden de columnas (por defecto REQUIRED_COLUMNS)
    """
    if columns is None:
        columns = list(REQUIRED_COLUMNS)
    header = ",".join(columns)
    data_lines = [
        _build_csv_row(username, display_name, status, email, user_id, columns)
        for username, display_name, status, email, user_id in rows
    ]
    return header + "\n" + "\n".join(data_lines) + "\n"


# =============================================================================
# Tests de propiedad
# =============================================================================


class TestRosterValidationProperty:
    """
    Property 12: Validación de roster CSV.

    Para cualquier contenido string, el validador de roster DEBE aceptarlo
    si y solo si es CSV válido con delimitador por comas, contiene las columnas
    requeridas en el encabezado, y tiene al menos 1 fila de datos; de lo
    contrario DEBE rechazarlo con un mensaje de error específico.
    """

    @settings(max_examples=100)
    @given(
        rows=st.lists(
            _valid_row,
            min_size=1,
            max_size=10,
        )
    )
    def test_csv_valido_siempre_produce_valid_true(self, rows):
        """
        Propiedad: CSV válido (encabezado correcto + al menos 1 fila de datos)
        siempre produce valid=True con lista de usuarios.

        **Validates: Requirements 10.2, 10.3**
        """
        csv_content = _build_valid_csv(rows)
        result = validate_roster(csv_content)

        assert result.valid is True, (
            f"CSV válido debería ser aceptado, pero obtuvo error: {result.error}"
        )
        assert result.error is None
        assert len(result.users) > 0

    @settings(max_examples=100)
    @given(
        rows=st.lists(_valid_row, min_size=1, max_size=5),
        columns_to_remove=st.lists(
            st.sampled_from(REQUIRED_COLUMNS),
            min_size=1,
            max_size=4,
            unique=True,
        ),
    )
    def test_csv_sin_columnas_requeridas_produce_error_columnas_faltantes(
        self, rows, columns_to_remove
    ):
        """
        Propiedad: CSV con columnas requeridas faltantes siempre produce
        valid=False con "Columnas faltantes" en el mensaje de error.

        **Validates: Requirements 10.2, 10.3**
        """
        # Construir encabezado sin las columnas removidas
        remaining_columns = [
            col for col in REQUIRED_COLUMNS if col not in columns_to_remove
        ]
        # Necesitamos al menos una columna para que sea un CSV parseable
        if not remaining_columns:
            remaining_columns = ["OtraColumna"]

        header = ",".join(remaining_columns)
        # Generar filas con el número correcto de campos
        data_lines = [
            ",".join(["valor"] * len(remaining_columns))
            for _ in rows
        ]
        csv_content = header + "\n" + "\n".join(data_lines) + "\n"

        result = validate_roster(csv_content)

        assert result.valid is False, (
            "CSV con columnas faltantes debería ser rechazado"
        )
        assert "Columnas faltantes" in result.error, (
            f"Error debería mencionar 'Columnas faltantes', obtuvo: {result.error}"
        )

    @settings(max_examples=100)
    @given(
        # Generar variaciones del encabezado con posibles espacios extra
        extra_whitespace=st.booleans(),
    )
    def test_csv_solo_encabezado_sin_datos_produce_error(self, extra_whitespace):
        """
        Propiedad: CSV con solo encabezado (sin filas de datos) siempre
        produce valid=False con "sin datos" en el mensaje de error.

        **Validates: Requirements 10.2, 10.3**
        """
        if extra_whitespace:
            header = ", ".join(REQUIRED_COLUMNS)
        else:
            header = ",".join(REQUIRED_COLUMNS)

        csv_content = header + "\n"

        result = validate_roster(csv_content)

        assert result.valid is False, (
            "CSV sin filas de datos debería ser rechazado"
        )
        assert "sin datos" in result.error, (
            f"Error debería mencionar 'sin datos', obtuvo: {result.error}"
        )

    @settings(max_examples=100)
    @given(
        content=st.one_of(
            st.just(""),
            st.just("   "),
            st.just("\n"),
            st.just("\n\n\n"),
            st.just("  \n  \n  "),
            st.text(
                alphabet=st.sampled_from(" \t\n\r"),
                min_size=0,
                max_size=20,
            ),
        )
    )
    def test_contenido_vacio_o_whitespace_produce_error(self, content):
        """
        Propiedad: Contenido vacío o solo whitespace siempre produce
        valid=False.

        **Validates: Requirements 10.2, 10.3**
        """
        result = validate_roster(content)

        assert result.valid is False, (
            f"Contenido vacío/whitespace debería ser rechazado: repr={repr(content)}"
        )
        assert result.users == []

    @settings(max_examples=100)
    @given(
        rows=st.lists(
            _valid_row,
            min_size=1,
            max_size=15,
        )
    )
    def test_csv_valido_retorna_numero_correcto_de_usuarios(self, rows):
        """
        Propiedad: CSV válido siempre retorna el número correcto de objetos
        User correspondiente a las filas de datos.

        **Validates: Requirements 10.2, 10.3**
        """
        csv_content = _build_valid_csv(rows)
        result = validate_roster(csv_content)

        assert result.valid is True
        assert len(result.users) == len(rows), (
            f"Esperaba {len(rows)} usuarios, obtuvo {len(result.users)}"
        )

    @settings(max_examples=100)
    @given(
        rows=st.lists(_valid_row, min_size=1, max_size=8),
        column_order=st.permutations(list(REQUIRED_COLUMNS)),
    )
    def test_orden_columnas_no_importa(self, rows, column_order):
        """
        Propiedad: El orden de las columnas en el encabezado no importa,
        siempre que todas las columnas requeridas estén presentes.

        **Validates: Requirements 10.2, 10.3**
        """
        csv_content = _build_valid_csv(rows, columns=list(column_order))
        result = validate_roster(csv_content)

        assert result.valid is True, (
            f"CSV con columnas en orden {column_order} debería ser válido, "
            f"pero obtuvo error: {result.error}"
        )
        assert len(result.users) == len(rows)
        # Verificar que los datos se mapean correctamente independiente del orden
        # El validador hace strip() de los valores, así que comparamos con strip()
        first_row = rows[0]
        first_user = result.users[0]
        assert first_user.username == first_row[0].strip()
        assert first_user.display_name == first_row[1].strip()
        assert first_user.status == first_row[2].strip()
        assert first_user.email == first_row[3].strip()
        assert first_user.user_id == first_row[4].strip()
