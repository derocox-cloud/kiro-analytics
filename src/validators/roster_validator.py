"""
Validador del archivo de roster CSV de usuarios.

Verifica que el contenido CSV cumpla con la estructura requerida:
codificación UTF-8, delimitador por comas, columnas obligatorias y
al menos una fila de datos válida.
"""
import csv
import io
from typing import List

from src.models import RosterValidationResult, User


# Columnas requeridas en el encabezado del roster
REQUIRED_COLUMNS: List[str] = [
    "Username",
    "Display name",
    "Status",
    "Email",
    "User ID",
]


def validate_roster(csv_content: str) -> RosterValidationResult:
    """
    Valida el contenido de un archivo CSV de roster de usuarios.

    Verifica:
    - Que el contenido sea texto válido (UTF-8 implícito al recibir str)
    - Que use delimitador por comas
    - Que contenga las columnas requeridas en el encabezado
    - Que tenga al menos 1 fila de datos válida además del encabezado

    Args:
        csv_content: Contenido del archivo CSV como string.

    Returns:
        RosterValidationResult con valid=True y lista de usuarios si es válido,
        o valid=False con mensaje de error específico si no lo es.
    """
    # Verificar que el contenido no esté vacío
    if not csv_content or not csv_content.strip():
        return RosterValidationResult(
            valid=False,
            users=[],
            error="Archivo sin datos de usuarios: el contenido está vacío",
        )

    # Intentar parsear como CSV con delimitador por comas
    try:
        reader = csv.DictReader(io.StringIO(csv_content), delimiter=",")
        fieldnames = reader.fieldnames
    except Exception as e:
        return RosterValidationResult(
            valid=False,
            users=[],
            error=f"Formato CSV inválido: {str(e)}",
        )

    # Verificar que se pudieron leer los nombres de columnas
    if not fieldnames:
        return RosterValidationResult(
            valid=False,
            users=[],
            error="Formato CSV inválido: no se encontró encabezado",
        )

    # Verificar presencia de columnas requeridas
    # Normalizar nombres de columnas (strip de espacios)
    normalized_fieldnames = [col.strip() for col in fieldnames]
    missing_columns = [
        col for col in REQUIRED_COLUMNS if col not in normalized_fieldnames
    ]

    if missing_columns:
        return RosterValidationResult(
            valid=False,
            users=[],
            error=f"Columnas faltantes en el encabezado: {', '.join(missing_columns)}",
        )

    # Leer filas de datos y construir lista de usuarios
    users: List[User] = []
    for row in reader:
        # Normalizar claves del row (strip de espacios en nombres de columna)
        normalized_row = {k.strip(): v.strip() if v else "" for k, v in row.items()}

        # Verificar que la fila tenga datos mínimos (al menos username y user_id)
        username = normalized_row.get("Username", "").strip()
        user_id = normalized_row.get("User ID", "").strip()

        if not username and not user_id:
            # Fila vacía, la ignoramos
            continue

        user = User(
            user_id=user_id,
            username=username,
            display_name=normalized_row.get("Display name", "").strip(),
            email=normalized_row.get("Email", "").strip(),
            status=normalized_row.get("Status", "").strip(),
        )
        users.append(user)

    # Verificar al menos 1 fila de datos válida
    if not users:
        return RosterValidationResult(
            valid=False,
            users=[],
            error="Archivo sin datos de usuarios: no se encontraron filas de datos válidas",
        )

    return RosterValidationResult(valid=True, users=users, error=None)
