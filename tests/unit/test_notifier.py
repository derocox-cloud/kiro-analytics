"""Tests unitarios para src/notifiers/notifier.py"""
from __future__ import annotations

import os

import boto3
import pytest
from moto import mock_aws

from src.models import ExecutionResult, NotificationResult
from src.notifiers.notifier import (
    MAX_RECIPIENTS,
    MIN_RECIPIENTS,
    _build_cloudwatch_logs_url,
    _build_failure_body,
    _build_failure_subject,
    _build_success_body,
    _build_success_subject,
    _validate_recipients,
    notify,
)

TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:kiro-analytics-notifications"


def _make_execution_result(
    status: str = "SUCCEEDED",
    period: str = "weekly",
    reference_date: str = "2026-05-05",
    users_processed: int = 15,
    failure_stage: str = None,
    failure_message: str = None,
) -> ExecutionResult:
    """Helper para crear un ExecutionResult de prueba."""
    return ExecutionResult(
        execution_id="exec-123-abc",
        period=period,
        reference_date=reference_date,
        status=status,
        total_duration_seconds=45.2,
        stage_durations={"collection": 10.0, "processing": 20.0, "generation": 15.2},
        users_processed=users_processed,
        data_size_bytes=1024000,
        failure_stage=failure_stage,
        failure_message=failure_message,
        report_urls={"html": "https://s3.example.com/report.html", "csv": "https://s3.example.com/report.csv"},
        timestamp="2026-05-06T07:30:00Z",
    )


@pytest.fixture
def sns_client():
    """Crea un cliente SNS mock con un tópico configurado."""
    with mock_aws():
        client = boto3.client("sns", region_name="us-east-1")
        client.create_topic(Name="kiro-analytics-notifications")
        yield client


@pytest.fixture
def set_sns_env(monkeypatch):
    """Configura la variable de entorno SNS_TOPIC_ARN."""
    monkeypatch.setenv("SNS_TOPIC_ARN", TOPIC_ARN)


@pytest.fixture
def set_region_env(monkeypatch):
    """Configura la variable de entorno AWS_REGION."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")


class TestBuildSuccessSubject:
    """Tests para _build_success_subject."""

    def test_daily_subject(self):
        """Genera asunto correcto para reporte diario."""
        subject = _build_success_subject("daily", "2026-05-05")
        assert "Diario" in subject
        assert "2026-05-05" in subject
        assert "✅" in subject

    def test_weekly_subject(self):
        """Genera asunto correcto para reporte semanal."""
        subject = _build_success_subject("weekly", "2026-05-05")
        assert "Semanal" in subject
        assert "2026-05-05" in subject

    def test_monthly_subject(self):
        """Genera asunto correcto para reporte mensual."""
        subject = _build_success_subject("monthly", "2026-03-01")
        assert "Mensual" in subject
        assert "2026-03-01" in subject


class TestBuildFailureSubject:
    """Tests para _build_failure_subject."""

    def test_daily_failure_subject(self):
        """Genera asunto de fallo correcto para reporte diario."""
        subject = _build_failure_subject("daily", "2026-05-05")
        assert "Fallo" in subject
        assert "Diario" in subject
        assert "2026-05-05" in subject
        assert "❌" in subject

    def test_weekly_failure_subject(self):
        """Genera asunto de fallo correcto para reporte semanal."""
        subject = _build_failure_subject("weekly", "2026-05-05")
        assert "Semanal" in subject


class TestBuildSuccessBody:
    """Tests para _build_success_body."""

    def test_includes_users_processed(self):
        """El cuerpo incluye número de usuarios procesados."""
        result = _make_execution_result(users_processed=20)
        body = _build_success_body(result, {"html": "https://example.com/report.html"})
        assert "20" in body

    def test_includes_report_urls(self):
        """El cuerpo incluye URLs pre-firmadas de reportes."""
        urls = {"html": "https://s3.example.com/report.html", "csv": "https://s3.example.com/report.csv"}
        result = _make_execution_result()
        body = _build_success_body(result, urls)
        assert "https://s3.example.com/report.html" in body
        assert "https://s3.example.com/report.csv" in body

    def test_includes_duration(self):
        """El cuerpo incluye la duración total."""
        result = _make_execution_result()
        body = _build_success_body(result, None)
        assert "45.2" in body

    def test_includes_period_and_date(self):
        """El cuerpo incluye periodo y fecha de referencia."""
        result = _make_execution_result(period="monthly", reference_date="2026-03-01")
        body = _build_success_body(result, None)
        assert "monthly" in body
        assert "2026-03-01" in body

    def test_no_report_urls_shows_warning(self):
        """Muestra advertencia si no hay URLs de reportes."""
        result = _make_execution_result()
        body = _build_success_body(result, None)
        assert "No se generaron URLs" in body


class TestBuildFailureBody:
    """Tests para _build_failure_body."""

    def test_includes_failure_stage(self, set_region_env):
        """El cuerpo incluye la etapa fallida."""
        result = _make_execution_result(
            status="FAILED",
            failure_stage="processing",
            failure_message="DynamoDB write error",
        )
        body = _build_failure_body(result)
        assert "processing" in body

    def test_includes_failure_message(self, set_region_env):
        """El cuerpo incluye el mensaje de error."""
        result = _make_execution_result(
            status="FAILED",
            failure_stage="collection",
            failure_message="S3 access denied",
        )
        body = _build_failure_body(result)
        assert "S3 access denied" in body

    def test_includes_cloudwatch_link(self, set_region_env):
        """El cuerpo incluye enlace a CloudWatch Logs."""
        result = _make_execution_result(
            status="FAILED",
            failure_stage="collection",
            failure_message="Error",
        )
        body = _build_failure_body(result)
        assert "console.aws.amazon.com/cloudwatch" in body
        assert "exec-123-abc" in body

    def test_handles_none_failure_fields(self, set_region_env):
        """Maneja campos de fallo nulos sin error."""
        result = _make_execution_result(
            status="FAILED",
            failure_stage=None,
            failure_message=None,
        )
        body = _build_failure_body(result)
        assert "Desconocida" in body
        assert "Sin mensaje de error" in body


class TestBuildCloudwatchLogsUrl:
    """Tests para _build_cloudwatch_logs_url."""

    def test_contains_region(self):
        """La URL contiene la región."""
        url = _build_cloudwatch_logs_url("exec-1", "us-east-1")
        assert "us-east-1" in url

    def test_contains_execution_id(self):
        """La URL contiene el ID de ejecución."""
        url = _build_cloudwatch_logs_url("exec-test-123", "us-east-1")
        assert "exec-test-123" in url

    def test_points_to_cloudwatch(self):
        """La URL apunta a la consola de CloudWatch."""
        url = _build_cloudwatch_logs_url("exec-1", "eu-west-1")
        assert "console.aws.amazon.com/cloudwatch" in url


class TestValidateRecipients:
    """Tests para _validate_recipients."""

    def test_valid_list_single(self):
        """Lista con un destinatario es válida."""
        assert _validate_recipients(["user@example.com"]) is None

    def test_valid_list_multiple(self):
        """Lista con múltiples destinatarios es válida."""
        recipients = [f"user{i}@example.com" for i in range(5)]
        assert _validate_recipients(recipients) is None

    def test_valid_list_max(self):
        """Lista con máximo (10) destinatarios es válida."""
        recipients = [f"user{i}@example.com" for i in range(MAX_RECIPIENTS)]
        assert _validate_recipients(recipients) is None

    def test_empty_list_invalid(self):
        """Lista vacía es inválida."""
        error = _validate_recipients([])
        assert error is not None
        assert "vacía" in error

    def test_too_many_recipients(self):
        """Más de 10 destinatarios es inválido."""
        recipients = [f"user{i}@example.com" for i in range(11)]
        error = _validate_recipients(recipients)
        assert error is not None
        assert "10" in error


class TestNotify:
    """Tests para la función principal notify."""

    def test_success_notification(self, sns_client, set_sns_env, set_region_env):
        """Envía notificación exitosa correctamente."""
        result_exec = _make_execution_result(status="SUCCEEDED")
        urls = {"html": "https://s3.example.com/report.html"}
        recipients = ["admin@example.com"]

        result = notify(result_exec, urls, recipients, sns_client=sns_client)

        assert result.success is True
        assert result.error is None

    def test_failure_notification(self, sns_client, set_sns_env, set_region_env):
        """Envía notificación de fallo correctamente."""
        result_exec = _make_execution_result(
            status="FAILED",
            failure_stage="processing",
            failure_message="DynamoDB timeout",
        )
        recipients = ["admin@example.com", "lead@example.com"]

        result = notify(result_exec, None, recipients, sns_client=sns_client)

        assert result.success is True
        assert result.error is None

    def test_empty_recipients_returns_error(self, set_sns_env):
        """Retorna error si la lista de destinatarios está vacía."""
        result_exec = _make_execution_result()

        result = notify(result_exec, None, [], sns_client=None)

        assert result.success is False
        assert "vacía" in result.error

    def test_too_many_recipients_returns_error(self, set_sns_env):
        """Retorna error si hay más de 10 destinatarios."""
        result_exec = _make_execution_result()
        recipients = [f"user{i}@example.com" for i in range(11)]

        result = notify(result_exec, None, recipients, sns_client=None)

        assert result.success is False
        assert "10" in result.error

    def test_missing_topic_arn_returns_error(self, monkeypatch):
        """Retorna error si SNS_TOPIC_ARN no está configurado."""
        monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)
        result_exec = _make_execution_result()

        result = notify(result_exec, None, ["user@example.com"], sns_client=None)

        assert result.success is False
        assert "SNS_TOPIC_ARN" in result.error

    def test_sns_failure_does_not_raise(self, set_sns_env, set_region_env):
        """Si SNS falla, retorna error sin lanzar excepción."""
        with mock_aws():
            # Crear cliente sin el tópico para provocar error
            client = boto3.client("sns", region_name="us-east-1")
            result_exec = _make_execution_result()

            # Usar un ARN de tópico que no existe
            result = notify(
                result_exec,
                {"html": "https://example.com"},
                ["user@example.com"],
                sns_client=client,
            )

            # No debe lanzar excepción - registra error y retorna
            assert result.success is False
            assert result.error is not None

    def test_does_not_affect_pipeline_state(self, set_sns_env, set_region_env):
        """El fallo de notificación no lanza excepciones (no afecta pipeline)."""
        with mock_aws():
            client = boto3.client("sns", region_name="us-east-1")
            result_exec = _make_execution_result()

            # Esto no debe lanzar una excepción
            result = notify(
                result_exec,
                None,
                ["user@example.com"],
                sns_client=client,
            )

            # Solo retorna NotificationResult, nunca lanza
            assert isinstance(result, NotificationResult)

    def test_multiple_recipients(self, sns_client, set_sns_env, set_region_env):
        """Funciona con múltiples destinatarios dentro del rango permitido."""
        result_exec = _make_execution_result()
        recipients = [f"user{i}@example.com" for i in range(5)]

        result = notify(result_exec, None, recipients, sns_client=sns_client)

        assert result.success is True
