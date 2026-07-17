"""Tests unitarios para src/generators/site_publisher.py"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from src.generators.site_publisher import (
    MAX_PUBLISH_TIME_SECONDS,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
    publish_report,
)

BUCKET = "test-site-reportes"
FILENAME = "kiro_report_daily_2026-01-15_2026-01-15.html"
HTML_CONTENT = "<html><body><h1>Reporte Diario</h1></body></html>"


@pytest.fixture
def s3_client():
    """Crea un cliente S3 mock con el bucket del sitio de reportes."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


class TestPublishReportSuccess:
    """Tests para publicación exitosa de reportes."""

    def test_publica_reporte_exitosamente(self, s3_client):
        """Publica un reporte HTML y retorna True."""
        result = publish_report(
            html_content=HTML_CONTENT,
            filename=FILENAME,
            bucket=BUCKET,
            s3_client=s3_client,
        )

        assert result is True

    def test_contenido_subido_coincide(self, s3_client):
        """El contenido subido a S3 coincide con el original."""
        publish_report(
            html_content=HTML_CONTENT,
            filename=FILENAME,
            bucket=BUCKET,
            s3_client=s3_client,
        )

        response = s3_client.get_object(Bucket=BUCKET, Key=FILENAME)
        body = response["Body"].read().decode("utf-8")
        assert body == HTML_CONTENT

    def test_content_type_es_text_html(self, s3_client):
        """El content-type del objeto subido es text/html."""
        publish_report(
            html_content=HTML_CONTENT,
            filename=FILENAME,
            bucket=BUCKET,
            s3_client=s3_client,
        )

        response = s3_client.get_object(Bucket=BUCKET, Key=FILENAME)
        assert response["ContentType"] == "text/html"

    def test_mantiene_nomenclatura_original(self, s3_client):
        """Mantiene la nomenclatura original del archivo."""
        filename = "kiro_report_weekly_2026-05-05_2026-05-11.html"
        publish_report(
            html_content=HTML_CONTENT,
            filename=filename,
            bucket=BUCKET,
            s3_client=s3_client,
        )

        # Verificar que el objeto existe con el nombre exacto
        response = s3_client.list_objects_v2(Bucket=BUCKET, Prefix=filename)
        assert response["KeyCount"] == 1
        assert response["Contents"][0]["Key"] == filename

    def test_soporta_contenido_con_acentos(self, s3_client):
        """Publica correctamente contenido con caracteres especiales."""
        html = "<html><body><h1>Análisis de métricas</h1></body></html>"
        publish_report(
            html_content=html,
            filename=FILENAME,
            bucket=BUCKET,
            s3_client=s3_client,
        )

        response = s3_client.get_object(Bucket=BUCKET, Key=FILENAME)
        body = response["Body"].read().decode("utf-8")
        assert body == html


class TestPublishReportRetries:
    """Tests para lógica de reintentos."""

    def test_reintenta_hasta_2_veces_en_fallo(self):
        """Reintenta hasta 2 veces si la publicación falla."""
        mock_client = MagicMock()
        error_response = {"Error": {"Code": "InternalError", "Message": "Error interno"}}
        mock_client.put_object.side_effect = ClientError(error_response, "PutObject")

        with patch("src.generators.site_publisher.time.sleep"):
            result = publish_report(
                html_content=HTML_CONTENT,
                filename=FILENAME,
                bucket=BUCKET,
                s3_client=mock_client,
            )

        assert result is False
        # 1 intento inicial + 2 reintentos = 3 llamadas
        assert mock_client.put_object.call_count == 1 + MAX_RETRIES

    def test_retorna_true_si_segundo_intento_exitoso(self):
        """Retorna True si el reintento es exitoso."""
        mock_client = MagicMock()
        error_response = {"Error": {"Code": "InternalError", "Message": "Error"}}
        # Primer intento falla, segundo exitoso
        mock_client.put_object.side_effect = [
            ClientError(error_response, "PutObject"),
            None,  # Éxito en segundo intento
        ]

        with patch("src.generators.site_publisher.time.sleep"):
            result = publish_report(
                html_content=HTML_CONTENT,
                filename=FILENAME,
                bucket=BUCKET,
                s3_client=mock_client,
            )

        assert result is True
        assert mock_client.put_object.call_count == 2

    def test_retorna_true_si_tercer_intento_exitoso(self):
        """Retorna True si el último reintento es exitoso."""
        mock_client = MagicMock()
        error_response = {"Error": {"Code": "InternalError", "Message": "Error"}}
        # Primeros dos intentos fallan, tercero exitoso
        mock_client.put_object.side_effect = [
            ClientError(error_response, "PutObject"),
            ClientError(error_response, "PutObject"),
            None,  # Éxito en tercer intento
        ]

        with patch("src.generators.site_publisher.time.sleep"):
            result = publish_report(
                html_content=HTML_CONTENT,
                filename=FILENAME,
                bucket=BUCKET,
                s3_client=mock_client,
            )

        assert result is True
        assert mock_client.put_object.call_count == 3

    def test_espera_entre_reintentos(self):
        """Espera RETRY_DELAY_SECONDS entre reintentos."""
        mock_client = MagicMock()
        error_response = {"Error": {"Code": "InternalError", "Message": "Error"}}
        mock_client.put_object.side_effect = ClientError(error_response, "PutObject")

        with patch("src.generators.site_publisher.time.sleep") as mock_sleep:
            publish_report(
                html_content=HTML_CONTENT,
                filename=FILENAME,
                bucket=BUCKET,
                s3_client=mock_client,
            )

        # Se espera entre reintentos (2 esperas para 2 reintentos)
        assert mock_sleep.call_count == MAX_RETRIES
        for call in mock_sleep.call_args_list:
            assert call[0][0] == RETRY_DELAY_SECONDS


class TestPublishReportFailure:
    """Tests para fallos de publicación."""

    def test_retorna_false_si_bucket_no_existe(self):
        """Retorna False si el bucket no existe después de reintentos."""
        with mock_aws():
            client = boto3.client("s3", region_name="us-east-1")
            # No creamos el bucket

            with patch("src.generators.site_publisher.time.sleep"):
                result = publish_report(
                    html_content=HTML_CONTENT,
                    filename=FILENAME,
                    bucket="bucket-inexistente",
                    s3_client=client,
                )

            assert result is False

    def test_retorna_false_si_timeout_excedido(self):
        """Retorna False si se excede el tiempo máximo de publicación."""
        mock_client = MagicMock()

        # Simular que el tiempo ya excedió el máximo
        with patch("src.generators.site_publisher.time.time") as mock_time:
            mock_time.side_effect = [0, MAX_PUBLISH_TIME_SECONDS + 1]
            result = publish_report(
                html_content=HTML_CONTENT,
                filename=FILENAME,
                bucket=BUCKET,
                s3_client=mock_client,
            )

        assert result is False
        # No debería intentar subir si el tiempo ya expiró
        mock_client.put_object.assert_not_called()

    def test_no_lanza_excepcion_en_fallo(self):
        """No lanza excepción cuando falla; retorna False."""
        mock_client = MagicMock()
        error_response = {"Error": {"Code": "AccessDenied", "Message": "Acceso denegado"}}
        mock_client.put_object.side_effect = ClientError(error_response, "PutObject")

        with patch("src.generators.site_publisher.time.sleep"):
            # No debe lanzar excepción
            result = publish_report(
                html_content=HTML_CONTENT,
                filename=FILENAME,
                bucket=BUCKET,
                s3_client=mock_client,
            )

        assert result is False


class TestPublishReportConstants:
    """Tests para constantes del módulo."""

    def test_max_retries_es_2(self):
        """El número máximo de reintentos es 2."""
        assert MAX_RETRIES == 2

    def test_max_publish_time_es_60(self):
        """El tiempo máximo de publicación es 60 segundos."""
        assert MAX_PUBLISH_TIME_SECONDS == 60

    def test_retry_delay_es_5(self):
        """El tiempo de espera entre reintentos es 5 segundos."""
        assert RETRY_DELAY_SECONDS == 5
