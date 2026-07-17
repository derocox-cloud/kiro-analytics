"""
Tests unitarios para el handler del orquestador del pipeline.

Valida: validación de entrada, verificación de duplicados, emisión de
evento a EventBridge, y flujo principal del pipeline.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, ANY

import pytest

from src.orchestrator.handler import (
    _check_duplicate_execution,
    _determine_failure_stage,
    _emit_completion_event,
    _generate_execution_id,
    _get_notification_recipients,
    handler,
)


class TestGenerateExecutionId:
    """Tests para la generación de IDs de ejecución."""

    def test_genera_uuid_valido(self):
        """Genera un UUID v4 como ID de ejecución."""
        exec_id = _generate_execution_id()
        assert isinstance(exec_id, str)
        assert len(exec_id) == 36  # UUID formato estándar
        assert exec_id.count("-") == 4

    def test_genera_ids_unicos(self):
        """Cada invocación genera un ID diferente."""
        ids = {_generate_execution_id() for _ in range(100)}
        assert len(ids) == 100


class TestCheckDuplicateExecution:
    """Tests para la verificación de ejecuciones duplicadas."""

    def test_retorna_none_sin_duplicado(self):
        """Retorna None si no hay ejecución activa para el mismo periodo y fecha."""
        dynamodb_client = MagicMock()
        dynamodb_client.get_item.return_value = {}

        result = _check_duplicate_execution(
            dynamodb_client, "daily", "2026-05-15"
        )
        assert result is None

    def test_retorna_id_cuando_duplicado_activo(self):
        """Retorna el ID de la ejecución activa si hay duplicado."""
        dynamodb_client = MagicMock()
        dynamodb_client.get_item.return_value = {
            "Item": {
                "execution_key": {"S": "daily_2026-05-15"},
                "execution_id": {"S": "abc-123"},
                "status": {"S": "IN_PROGRESS"},
            }
        }

        result = _check_duplicate_execution(
            dynamodb_client, "daily", "2026-05-15"
        )
        assert result == "abc-123"

    def test_ignora_ejecucion_completada(self):
        """Ignora ejecuciones que ya finalizaron (status != IN_PROGRESS)."""
        dynamodb_client = MagicMock()
        dynamodb_client.get_item.return_value = {
            "Item": {
                "execution_key": {"S": "daily_2026-05-15"},
                "execution_id": {"S": "abc-123"},
                "status": {"S": "SUCCEEDED"},
            }
        }

        result = _check_duplicate_execution(
            dynamodb_client, "daily", "2026-05-15"
        )
        assert result is None

    def test_tabla_no_existe_retorna_none(self):
        """Si la tabla no existe, continúa sin bloquear."""
        from botocore.exceptions import ClientError

        dynamodb_client = MagicMock()
        dynamodb_client.get_item.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException"}},
            "GetItem",
        )

        result = _check_duplicate_execution(
            dynamodb_client, "daily", "2026-05-15"
        )
        assert result is None


class TestEmitCompletionEvent:
    """Tests para la emisión del evento de completación a EventBridge."""

    def test_emite_evento_con_datos_correctos(self):
        """Emite evento a EventBridge con periodo, fecha y rutas S3."""
        events_client = MagicMock()
        events_client.put_events.return_value = {}

        report_paths = {
            "html": "kiro_report_daily_2026-05-15_2026-05-15.html",
            "csv": "kiro_report_daily_2026-05-15_2026-05-15.csv",
        }

        _emit_completion_event(
            events_client=events_client,
            period="daily",
            reference_date="2026-05-15",
            report_paths=report_paths,
        )

        events_client.put_events.assert_called_once()
        call_args = events_client.put_events.call_args
        entries = call_args[1]["Entries"] if "Entries" in call_args[1] else call_args[0][0]

        entry = entries[0]
        assert entry["Source"] == "kiro.analytics.pipeline"
        assert entry["DetailType"] == "PipelineExecutionCompleted"

        detail = json.loads(entry["Detail"])
        assert detail["period"] == "daily"
        assert detail["reference_date"] == "2026-05-15"
        assert detail["report_paths"] == report_paths
        assert "timestamp" in detail


class TestDetermineFailureStage:
    """Tests para la determinación de la etapa de fallo."""

    def test_fallo_en_primera_etapa(self):
        """Si no hay duraciones registradas, el fallo es en la primera etapa."""
        result = _determine_failure_stage({})
        assert result == "lectura_roster"

    def test_fallo_en_recoleccion(self):
        """Si solo lectura_roster tiene duración, el fallo es en recolección."""
        result = _determine_failure_stage({"lectura_roster": 1.5})
        assert result == "recoleccion"

    def test_fallo_en_procesamiento(self):
        """Si roster y recolección completaron, el fallo es en procesamiento."""
        result = _determine_failure_stage({
            "lectura_roster": 1.0,
            "recoleccion": 5.0,
        })
        assert result == "procesamiento"

    def test_todas_etapas_completadas(self):
        """Si todas las etapas tienen duración, retorna 'desconocida'."""
        result = _determine_failure_stage({
            "lectura_roster": 1.0,
            "recoleccion": 5.0,
            "procesamiento": 3.0,
            "analisis_ai": 10.0,
            "generacion_reportes": 2.0,
            "publicacion": 1.0,
            "notificacion": 0.5,
        })
        assert result == "desconocida"


class TestGetNotificationRecipients:
    """Tests para obtener la lista de destinatarios."""

    @patch.dict("os.environ", {"NOTIFICATION_RECIPIENTS": ""})
    def test_retorna_lista_vacia_sin_configurar(self):
        """Retorna lista vacía si la variable de entorno está vacía."""
        # Re-importar para que tome el env actualizado
        from src.orchestrator import handler as h
        h.NOTIFICATION_RECIPIENTS = ""
        result = _get_notification_recipients()
        assert result == []

    @patch.dict("os.environ", {"NOTIFICATION_RECIPIENTS": "a@b.com,c@d.com"})
    def test_parsea_multiples_destinatarios(self):
        """Parsea correctamente múltiples destinatarios separados por coma."""
        from src.orchestrator import handler as h
        h.NOTIFICATION_RECIPIENTS = "a@b.com,c@d.com"
        result = _get_notification_recipients()
        assert result == ["a@b.com", "c@d.com"]


class TestHandlerValidation:
    """Tests para el flujo de validación del handler."""

    @patch("src.orchestrator.handler.boto3")
    def test_rechaza_periodo_invalido(self, mock_boto3):
        """El handler rechaza un periodo no válido con error descriptivo."""
        result = handler({"period": "biweekly", "reference_date": "2026-05-15"})

        assert result["status"] == "FAILED"
        assert "period" in result["error"].lower() or "period" in result["error"]
        assert result["stage"] == "validacion"

    @patch("src.orchestrator.handler.boto3")
    def test_rechaza_fecha_invalida(self, mock_boto3):
        """El handler rechaza una fecha con formato inválido."""
        result = handler({"period": "daily", "reference_date": "15-05-2026"})

        assert result["status"] == "FAILED"
        assert "reference_date" in result["error"]
        assert result["stage"] == "validacion"

    @patch("src.orchestrator.handler.boto3")
    def test_rechaza_ejecucion_duplicada(self, mock_boto3):
        """El handler rechaza si hay una ejecución duplicada activa."""
        # Mock DynamoDB para retornar ejecución activa
        mock_dynamodb = MagicMock()
        mock_dynamodb.get_item.return_value = {
            "Item": {
                "execution_key": {"S": "daily_2026-05-15"},
                "execution_id": {"S": "existing-exec-id"},
                "status": {"S": "IN_PROGRESS"},
            }
        }
        mock_boto3.client.return_value = mock_dynamodb

        result = handler({"period": "daily", "reference_date": "2026-05-15"})

        assert result["status"] == "FAILED"
        assert "duplicada" in result["error"].lower()
        assert result["stage"] == "verificacion_duplicados"
