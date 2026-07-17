"""
Tests unitarios para el recolector genérico de datos.

Verifica la lógica de recolección, filtrado por usuarios habilitados,
paginación S3, y manejo de resultados vacíos.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.collectors.collector import (
    _get_enabled_user_ids,
    _normalize_user_id,
    _parse_csv_records,
    _parse_json_gz_records,
    collect,
)
from src.models import CollectionResult, CollectorConfig, User


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def enabled_users():
    """Roster con usuarios habilitados y deshabilitados."""
    return [
        User(user_id="user-001", username="alice", display_name="Alice A", email="alice@test.com", status="Enabled"),
        User(user_id="user-002", username="bob", display_name="Bob B", email="bob@test.com", status="Enabled"),
        User(user_id="user-003", username="charlie", display_name="Charlie C", email="charlie@test.com", status="Disabled"),
    ]


@pytest.fixture
def csv_config():
    """Configuración para fuente CSV (user_report)."""
    return CollectorConfig(
        source_type="user_report",
        s3_prefix="dev-kiro-logs/AWSLogs/123456/KiroLogs/user_report/us-east-1",
        file_extension=".csv",
        max_files_per_day=1000,
    )


@pytest.fixture
def json_gz_config():
    """Configuración para fuente JSON.gz (prompts)."""
    return CollectorConfig(
        source_type="prompts",
        s3_prefix="prompt-metadata/AWSLogs/123456/KiroLogs/GenerateAssistantResponse/us-east-1",
        file_extension=".json.gz",
        max_files_per_day=500,
    )


# =============================================================================
# Tests para _get_enabled_user_ids
# =============================================================================


class TestGetEnabledUserIds:
    """Tests para la función de filtrado de IDs habilitados."""

    def test_filtra_solo_enabled(self, enabled_users):
        """Solo retorna IDs de usuarios con status Enabled."""
        result = _get_enabled_user_ids(enabled_users)
        assert result == {"user-001", "user-002"}

    def test_roster_vacio(self):
        """Retorna conjunto vacío si el roster está vacío."""
        result = _get_enabled_user_ids([])
        assert result == set()

    def test_ninguno_habilitado(self):
        """Retorna conjunto vacío si ningún usuario está habilitado."""
        users = [
            User(user_id="u1", username="x", display_name="X", email="x@t.com", status="Disabled"),
        ]
        result = _get_enabled_user_ids(users)
        assert result == set()


# =============================================================================
# Tests para _normalize_user_id
# =============================================================================


class TestNormalizeUserId:
    """Tests para la normalización de IDs de usuario."""

    def test_id_simple(self):
        """ID sin prefijo se retorna tal cual."""
        assert _normalize_user_id("user-001") == "user-001"

    def test_id_con_prefijo(self):
        """ID con prefijo d-XXXX. extrae la parte final."""
        assert _normalize_user_id("d-1234.user-001") == "user-001"

    def test_id_con_comillas(self):
        """Elimina comillas del ID."""
        assert _normalize_user_id('"user-001"') == "user-001"

    def test_id_con_prefijo_y_comillas(self):
        """Maneja prefijo y comillas simultáneamente."""
        assert _normalize_user_id('d-abc."user-001"') == "user-001"


# =============================================================================
# Tests para _parse_csv_records
# =============================================================================


class TestParseCsvRecords:
    """Tests para el parseo de registros CSV."""

    def test_filtra_por_usuarios_habilitados(self):
        """Solo incluye registros de usuarios habilitados."""
        csv_content = "UserId,Credits_Used,Chat_Conversations\nuser-001,10,5\nuser-003,20,3\n"
        enabled_ids = {"user-001", "user-002"}
        records = _parse_csv_records(csv_content, enabled_ids)
        assert len(records) == 1
        assert records[0]["_normalized_user_id"] == "user-001"

    def test_normaliza_user_id_con_prefijo(self):
        """Normaliza IDs con prefijo antes de filtrar."""
        csv_content = "UserId,Credits_Used\nd-123.user-001,10\n"
        enabled_ids = {"user-001"}
        records = _parse_csv_records(csv_content, enabled_ids)
        assert len(records) == 1
        assert records[0]["_normalized_user_id"] == "user-001"

    def test_csv_vacio(self):
        """Retorna lista vacía para CSV sin datos."""
        csv_content = "UserId,Credits_Used\n"
        enabled_ids = {"user-001"}
        records = _parse_csv_records(csv_content, enabled_ids)
        assert records == []


# =============================================================================
# Tests para _parse_json_gz_records
# =============================================================================


class TestParseJsonGzRecords:
    """Tests para el parseo de registros JSON.gz (prompts)."""

    def test_filtra_por_usuarios_habilitados(self):
        """Solo incluye registros de usuarios habilitados."""
        data = {
            "records": [
                {"generateAssistantResponseEventRequest": {"userId": "user-001", "prompt": "test"}},
                {"generateAssistantResponseEventRequest": {"userId": "user-003", "prompt": "test2"}},
            ]
        }
        enabled_ids = {"user-001"}
        records = _parse_json_gz_records(data, enabled_ids)
        assert len(records) == 1
        assert records[0]["_normalized_user_id"] == "user-001"

    def test_normaliza_user_id_con_prefijo(self):
        """Normaliza IDs con prefijo antes de filtrar."""
        data = {
            "records": [
                {"generateAssistantResponseEventRequest": {"userId": "d-abc.user-002", "prompt": "hi"}},
            ]
        }
        enabled_ids = {"user-002"}
        records = _parse_json_gz_records(data, enabled_ids)
        assert len(records) == 1

    def test_sin_records(self):
        """Retorna lista vacía si no hay campo records."""
        data = {}
        enabled_ids = {"user-001"}
        records = _parse_json_gz_records(data, enabled_ids)
        assert records == []


# =============================================================================
# Tests para collect (función principal)
# =============================================================================


class TestCollect:
    """Tests de integración para la función collect."""

    def test_retorna_resultado_vacio_sin_archivos(self, csv_config, enabled_users):
        """Retorna resultado vacío sin error si no hay archivos."""
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": []}]
        mock_s3.get_paginator.return_value = mock_paginator

        result = collect(
            config=csv_config,
            roster=enabled_users,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            execution_id="exec-001",
            s3_client=mock_s3,
            bucket="test-bucket",
            temp_bucket="temp-bucket",
        )

        assert isinstance(result, CollectionResult)
        assert result.records == []
        assert result.file_count == 0
        assert result.errors == []

    def test_recolecta_csv_y_filtra_usuarios(self, csv_config, enabled_users):
        """Recolecta archivos CSV y filtra por usuarios habilitados."""
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "prefix/2026/05/01/report.csv", "Size": 100},
                ]
            }
        ]
        mock_s3.get_paginator.return_value = mock_paginator

        # Simular descarga de CSV
        csv_body = "UserId,Credits_Used,Chat_Conversations\nuser-001,10,5\nuser-003,20,3\n"
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=csv_body.encode("utf-8")))
        }

        result = collect(
            config=csv_config,
            roster=enabled_users,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            execution_id="exec-001",
            s3_client=mock_s3,
            bucket="test-bucket",
            temp_bucket="temp-bucket",
        )

        assert result.file_count == 1
        assert len(result.records) == 1
        assert result.records[0]["_normalized_user_id"] == "user-001"
        assert result.data_size_bytes == 100

    def test_respeta_limite_archivos_por_dia(self, enabled_users):
        """Respeta max_files_per_day y no procesa más archivos."""
        config = CollectorConfig(
            source_type="prompts",
            s3_prefix="prefix",
            file_extension=".csv",
            max_files_per_day=2,
        )

        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        # 5 archivos disponibles pero límite es 2
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": f"prefix/2026/05/01/file{i}.csv", "Size": 50}
                    for i in range(5)
                ]
            }
        ]
        mock_s3.get_paginator.return_value = mock_paginator

        csv_body = "UserId,Credits_Used\nuser-001,10\n"
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=csv_body.encode("utf-8")))
        }

        result = collect(
            config=config,
            roster=enabled_users,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            execution_id="exec-001",
            s3_client=mock_s3,
            bucket="test-bucket",
            temp_bucket="temp-bucket",
        )

        assert result.file_count == 2

    def test_almacena_resultado_en_s3_temporal(self, csv_config, enabled_users):
        """Almacena resultado en S3 temporal con prefijo correcto."""
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "prefix/2026/05/01/report.csv", "Size": 100},
                ]
            }
        ]
        mock_s3.get_paginator.return_value = mock_paginator

        csv_body = "UserId,Credits_Used\nuser-001,10\n"
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=csv_body.encode("utf-8")))
        }

        result = collect(
            config=csv_config,
            roster=enabled_users,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            execution_id="exec-123",
            s3_client=mock_s3,
            bucket="test-bucket",
            temp_bucket="temp-bucket",
        )

        # Verificar que se llamó upload_json con el prefijo correcto
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "temp-bucket"
        assert call_kwargs["Key"] == "tmp/exec-123/user_report/data.json"

    def test_sin_cliente_s3_retorna_error(self, csv_config, enabled_users):
        """Retorna error si no se proporciona cliente S3."""
        result = collect(
            config=csv_config,
            roster=enabled_users,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            execution_id="exec-001",
            s3_client=None,
            bucket="test-bucket",
            temp_bucket="temp-bucket",
        )

        assert len(result.errors) == 1
        assert "Cliente S3" in result.errors[0]

    def test_roster_sin_usuarios_habilitados(self, csv_config):
        """Retorna resultado vacío si no hay usuarios habilitados."""
        disabled_users = [
            User(user_id="u1", username="x", display_name="X", email="x@t.com", status="Disabled"),
        ]

        mock_s3 = MagicMock()

        result = collect(
            config=csv_config,
            roster=disabled_users,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            execution_id="exec-001",
            s3_client=mock_s3,
            bucket="test-bucket",
            temp_bucket="temp-bucket",
        )

        assert result.records == []
        assert result.file_count == 0
        # No debería intentar listar objetos S3
        mock_s3.get_paginator.assert_not_called()

    def test_maneja_error_en_descarga(self, csv_config, enabled_users):
        """Continúa procesando si un archivo falla al descargarse."""
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "prefix/2026/05/01/bad.csv", "Size": 50},
                    {"Key": "prefix/2026/05/01/good.csv", "Size": 100},
                ]
            }
        ]
        mock_s3.get_paginator.return_value = mock_paginator

        # Primera llamada falla, segunda tiene éxito
        csv_body = "UserId,Credits_Used\nuser-001,10\n"
        mock_s3.get_object.side_effect = [
            Exception("S3 error"),
            {"Body": MagicMock(read=MagicMock(return_value=csv_body.encode("utf-8")))},
        ]

        result = collect(
            config=csv_config,
            roster=enabled_users,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            execution_id="exec-001",
            s3_client=mock_s3,
            bucket="test-bucket",
            temp_bucket="temp-bucket",
        )

        assert result.file_count == 1
        assert len(result.errors) == 1
        assert "bad.csv" in result.errors[0]

    def test_multiples_dias_en_rango(self, csv_config, enabled_users):
        """Procesa archivos de múltiples días en el rango."""
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        # Retorna un archivo por cada llamada de paginación
        mock_paginator.paginate.side_effect = [
            [{"Contents": [{"Key": "prefix/2026/05/01/r1.csv", "Size": 50}]}],
            [{"Contents": [{"Key": "prefix/2026/05/02/r2.csv", "Size": 60}]}],
        ]
        mock_s3.get_paginator.return_value = mock_paginator

        csv_body = "UserId,Credits_Used\nuser-001,10\n"
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=csv_body.encode("utf-8")))
        }

        result = collect(
            config=csv_config,
            roster=enabled_users,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 2),
            execution_id="exec-001",
            s3_client=mock_s3,
            bucket="test-bucket",
            temp_bucket="temp-bucket",
        )

        assert result.file_count == 2
        assert len(result.records) == 2
        assert result.data_size_bytes == 110
