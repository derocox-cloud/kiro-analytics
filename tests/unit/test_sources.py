"""
Tests unitarios para las configuraciones de fuentes de datos.

Verifica que las configuraciones de recolección por fuente sean correctas,
que los prefijos S3 coincidan con los del script original, y que la lectura
del roster desde S3 funcione correctamente.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.collectors.sources import (
    ANALYTICS_PREFIX,
    LOGS_BUCKET,
    PROMPTS_PREFIX,
    USER_REPORT_PREFIX,
    get_config_for_source,
    get_source_configs,
    read_roster_from_s3,
)
from src.models import CollectorConfig, User


# =============================================================================
# Tests para constantes y prefijos S3
# =============================================================================


class TestPrefijosS3:
    """Verifica que los prefijos S3 coincidan con el script original."""

    def test_bucket_correcto(self):
        """El bucket de logs es el esperado."""
        assert LOGS_BUCKET == "dev-logs-prompt-kiro-123456789012-us-east-1-an"

    def test_user_report_prefix(self):
        """Prefijo de user_report coincide con el script original."""
        assert USER_REPORT_PREFIX == (
            "dev-kiro-logs/AWSLogs/123456789012/KiroLogs/user_report/us-east-1"
        )

    def test_analytics_prefix(self):
        """Prefijo de by_user_analytic coincide con el script original."""
        assert ANALYTICS_PREFIX == (
            "dev-kiro-logs/AWSLogs/123456789012/KiroLogs/by_user_analytic/us-east-1"
        )

    def test_prompts_prefix(self):
        """Prefijo de prompt-metadata coincide con el script original."""
        assert PROMPTS_PREFIX == (
            "prompt-metadata/AWSLogs/123456789012/KiroLogs/"
            "GenerateAssistantResponse/us-east-1"
        )


# =============================================================================
# Tests para get_source_configs
# =============================================================================


class TestGetSourceConfigs:
    """Verifica las configuraciones de fuentes de datos."""

    def test_retorna_tres_fuentes(self):
        """Retorna exactamente tres configuraciones de fuentes."""
        configs = get_source_configs()
        assert len(configs) == 3
        assert set(configs.keys()) == {"user_report", "by_user_analytic", "prompt-metadata"}

    def test_user_report_config(self):
        """Configuración de user_report es correcta."""
        configs = get_source_configs()
        cfg = configs["user_report"]
        assert isinstance(cfg, CollectorConfig)
        assert cfg.source_type == "user_report"
        assert cfg.file_extension == ".csv"
        assert cfg.max_files_per_day == 0  # Sin límite

    def test_by_user_analytic_config(self):
        """Configuración de by_user_analytic es correcta."""
        configs = get_source_configs()
        cfg = configs["by_user_analytic"]
        assert isinstance(cfg, CollectorConfig)
        assert cfg.source_type == "by_user_analytic"
        assert cfg.file_extension == ".csv"
        assert cfg.max_files_per_day == 0  # Sin límite

    def test_prompt_metadata_config(self):
        """Configuración de prompt-metadata es correcta."""
        configs = get_source_configs()
        cfg = configs["prompt-metadata"]
        assert isinstance(cfg, CollectorConfig)
        assert cfg.source_type == "prompt-metadata"
        assert cfg.file_extension == ".json.gz"
        assert cfg.max_files_per_day == 500


# =============================================================================
# Tests para get_config_for_source
# =============================================================================


class TestGetConfigForSource:
    """Verifica la obtención de configuración por nombre de fuente."""

    def test_fuente_valida_user_report(self):
        """Retorna configuración correcta para user_report."""
        cfg = get_config_for_source("user_report")
        assert cfg.source_type == "user_report"

    def test_fuente_valida_by_user_analytic(self):
        """Retorna configuración correcta para by_user_analytic."""
        cfg = get_config_for_source("by_user_analytic")
        assert cfg.source_type == "by_user_analytic"

    def test_fuente_valida_prompt_metadata(self):
        """Retorna configuración correcta para prompt-metadata."""
        cfg = get_config_for_source("prompt-metadata")
        assert cfg.source_type == "prompt-metadata"

    def test_fuente_invalida_lanza_error(self):
        """Lanza ValueError para fuente no válida."""
        with pytest.raises(ValueError, match="Fuente de datos no válida"):
            get_config_for_source("fuente_inexistente")

    def test_error_incluye_fuentes_validas(self):
        """El mensaje de error incluye las fuentes válidas."""
        with pytest.raises(ValueError, match="user_report"):
            get_config_for_source("invalid")


# =============================================================================
# Tests para read_roster_from_s3
# =============================================================================


class TestReadRosterFromS3:
    """Verifica la lectura del roster de usuarios desde S3."""

    def _mock_s3_with_csv(self, csv_content: str) -> MagicMock:
        """Crea un mock de S3 que retorna el contenido CSV dado."""
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=csv_content.encode("utf-8")))
        }
        # Configurar exceptions para NoSuchKey
        mock_s3.exceptions = MagicMock()
        mock_s3.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
        return mock_s3

    def test_lee_roster_valido(self):
        """Lee y parsea correctamente un roster CSV válido."""
        csv_content = (
            "Username,Display name,Status,Email,User ID\n"
            "alice,Alice A,Enabled,alice@test.com,user-001\n"
            "bob,Bob B,Enabled,bob@test.com,user-002\n"
        )
        mock_s3 = self._mock_s3_with_csv(csv_content)

        users = read_roster_from_s3(mock_s3, "my-bucket", "config/roster.csv")

        assert len(users) == 2
        assert all(isinstance(u, User) for u in users)
        assert users[0].username == "alice"
        assert users[0].user_id == "user-001"
        assert users[1].username == "bob"

    def test_llama_s3_con_bucket_y_key_correctos(self):
        """Invoca S3 con el bucket y key proporcionados."""
        csv_content = (
            "Username,Display name,Status,Email,User ID\n"
            "alice,Alice A,Enabled,alice@test.com,user-001\n"
        )
        mock_s3 = self._mock_s3_with_csv(csv_content)

        read_roster_from_s3(mock_s3, "mi-bucket", "ruta/al/roster.csv")

        mock_s3.get_object.assert_called_once_with(
            Bucket="mi-bucket", Key="ruta/al/roster.csv"
        )

    def test_archivo_no_encontrado_lanza_error(self):
        """Lanza FileNotFoundError si el archivo no existe en S3."""
        mock_s3 = MagicMock()
        no_such_key_error = type("NoSuchKey", (Exception,), {})()
        mock_s3.exceptions.NoSuchKey = type(no_such_key_error)
        mock_s3.get_object.side_effect = mock_s3.exceptions.NoSuchKey("Not found")

        with pytest.raises(FileNotFoundError, match="no encontrado"):
            read_roster_from_s3(mock_s3, "bucket", "no-existe.csv")

    def test_csv_invalido_lanza_value_error(self):
        """Lanza ValueError si el CSV no tiene las columnas requeridas."""
        csv_content = "col1,col2\nval1,val2\n"
        mock_s3 = self._mock_s3_with_csv(csv_content)

        with pytest.raises(ValueError, match="Roster inválido"):
            read_roster_from_s3(mock_s3, "bucket", "bad-roster.csv")

    def test_csv_vacio_lanza_value_error(self):
        """Lanza ValueError si el CSV está vacío."""
        csv_content = ""
        mock_s3 = self._mock_s3_with_csv(csv_content)

        with pytest.raises(ValueError, match="Roster inválido"):
            read_roster_from_s3(mock_s3, "bucket", "empty.csv")

    def test_csv_solo_encabezado_lanza_value_error(self):
        """Lanza ValueError si el CSV solo tiene encabezado sin datos."""
        csv_content = "Username,Display name,Status,Email,User ID\n"
        mock_s3 = self._mock_s3_with_csv(csv_content)

        with pytest.raises(ValueError, match="Roster inválido"):
            read_roster_from_s3(mock_s3, "bucket", "header-only.csv")

    def test_incluye_usuarios_con_cualquier_status(self):
        """Retorna todos los usuarios del roster, independientemente del status."""
        csv_content = (
            "Username,Display name,Status,Email,User ID\n"
            "alice,Alice A,Enabled,alice@test.com,user-001\n"
            "bob,Bob B,Disabled,bob@test.com,user-002\n"
        )
        mock_s3 = self._mock_s3_with_csv(csv_content)

        users = read_roster_from_s3(mock_s3, "bucket", "roster.csv")

        # El roster_validator retorna todos los usuarios, el filtrado por
        # status Enabled se hace en el recolector
        assert len(users) == 2
