"""
Tests unitarios para el validador de roster CSV.

Verifica los diferentes escenarios de validación:
- CSV válido con datos correctos
- Contenido vacío
- Columnas faltantes
- Sin filas de datos
- Formato inválido
"""
import pytest

from src.validators.roster_validator import validate_roster


class TestValidateRoster:
    """Tests para la función validate_roster."""

    def test_csv_valido_con_usuarios(self):
        """Un CSV válido con columnas correctas y datos retorna valid=True."""
        csv_content = (
            "Username,Display name,Status,Email,User ID\n"
            "jdoe,John Doe,Enabled,jdoe@example.com,a42834d8-e041-70dc-81aa-13a3e6832554\n"
            "jsmith,Jane Smith,Enabled,jsmith@example.com,048864e8-3011-70e4-d43b-b332071a805c\n"
        )
        result = validate_roster(csv_content)

        assert result.valid is True
        assert result.error is None
        assert len(result.users) == 2
        assert result.users[0].username == "jdoe"
        assert result.users[0].display_name == "John Doe"
        assert result.users[0].status == "Enabled"
        assert result.users[0].email == "jdoe@example.com"
        assert result.users[0].user_id == "a42834d8-e041-70dc-81aa-13a3e6832554"

    def test_csv_valido_un_solo_usuario(self):
        """Un CSV con exactamente 1 fila de datos es válido."""
        csv_content = (
            "Username,Display name,Status,Email,User ID\n"
            "jdoe,John Doe,Enabled,jdoe@example.com,abc123\n"
        )
        result = validate_roster(csv_content)

        assert result.valid is True
        assert len(result.users) == 1

    def test_contenido_vacio(self):
        """Contenido vacío retorna error específico."""
        result = validate_roster("")

        assert result.valid is False
        assert result.users == []
        assert "vacío" in result.error

    def test_contenido_solo_espacios(self):
        """Contenido con solo espacios/newlines retorna error."""
        result = validate_roster("   \n  \n  ")

        assert result.valid is False
        assert "vacío" in result.error

    def test_columnas_faltantes(self):
        """CSV sin columnas requeridas retorna error con columnas faltantes."""
        csv_content = (
            "Username,Email\n"
            "jdoe,jdoe@example.com\n"
        )
        result = validate_roster(csv_content)

        assert result.valid is False
        assert "Columnas faltantes" in result.error
        assert "Display name" in result.error
        assert "Status" in result.error
        assert "User ID" in result.error

    def test_solo_encabezado_sin_datos(self):
        """CSV con solo encabezado y sin filas de datos retorna error."""
        csv_content = "Username,Display name,Status,Email,User ID\n"
        result = validate_roster(csv_content)

        assert result.valid is False
        assert "sin datos de usuarios" in result.error

    def test_encabezado_con_espacios(self):
        """CSV con espacios en nombres de columnas se normaliza correctamente."""
        csv_content = (
            "Username, Display name, Status, Email, User ID\n"
            "jdoe, John Doe, Enabled, jdoe@example.com, abc123\n"
        )
        result = validate_roster(csv_content)

        assert result.valid is True
        assert len(result.users) == 1
        assert result.users[0].username == "jdoe"
        assert result.users[0].display_name == "John Doe"

    def test_usuarios_con_diferentes_status(self):
        """El validador acepta usuarios con cualquier status."""
        csv_content = (
            "Username,Display name,Status,Email,User ID\n"
            "user1,User One,Enabled,user1@test.com,id1\n"
            "user2,User Two,Disabled,user2@test.com,id2\n"
        )
        result = validate_roster(csv_content)

        assert result.valid is True
        assert len(result.users) == 2
        assert result.users[0].status == "Enabled"
        assert result.users[1].status == "Disabled"

    def test_fila_completamente_vacia_se_ignora(self):
        """Filas vacías (sin username ni user_id) se ignoran."""
        csv_content = (
            "Username,Display name,Status,Email,User ID\n"
            ",,,,\n"
            "jdoe,John Doe,Enabled,jdoe@example.com,abc123\n"
        )
        result = validate_roster(csv_content)

        assert result.valid is True
        assert len(result.users) == 1

    def test_todas_filas_vacias_retorna_error(self):
        """Si todas las filas de datos están vacías, retorna error."""
        csv_content = (
            "Username,Display name,Status,Email,User ID\n"
            ",,,,\n"
            ",,,,\n"
        )
        result = validate_roster(csv_content)

        assert result.valid is False
        assert "sin datos de usuarios" in result.error

    def test_una_columna_faltante(self):
        """Falta una sola columna requerida."""
        csv_content = (
            "Username,Display name,Status,Email\n"
            "jdoe,John Doe,Enabled,jdoe@example.com\n"
        )
        result = validate_roster(csv_content)

        assert result.valid is False
        assert "User ID" in result.error
