"""Tests unitarios para src/generators/report_storage.py"""
from __future__ import annotations

import os

import boto3
import pytest
from moto import mock_aws

from src.generators.report_storage import (
    PRESIGNED_URL_EXPIRATION,
    _build_s3_key,
    _get_reports_bucket,
    store_reports,
)

BUCKET = "test-reports-bucket"


@pytest.fixture
def s3_client():
    """Crea un cliente S3 mock con un bucket de reportes."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


@pytest.fixture
def set_bucket_env(monkeypatch):
    """Configura la variable de entorno REPORTS_BUCKET."""
    monkeypatch.setenv("REPORTS_BUCKET", BUCKET)


class TestBuildS3Key:
    """Tests para _build_s3_key."""

    def test_daily_key(self):
        """Genera clave correcta para reporte diario HTML."""
        key = _build_s3_key("daily", "2026-01-15", "2026-01-15", "html")
        assert key == "reports/kiro_report_daily_2026-01-15_2026-01-15.html"

    def test_weekly_csv_key(self):
        """Genera clave correcta para reporte semanal CSV."""
        key = _build_s3_key("weekly", "2026-01-06", "2026-01-12", "csv")
        assert key == "reports/kiro_report_weekly_2026-01-06_2026-01-12.csv"

    def test_monthly_key(self):
        """Genera clave correcta para reporte mensual."""
        key = _build_s3_key("monthly", "2026-03-01", "2026-03-31", "html")
        assert key == "reports/kiro_report_monthly_2026-03-01_2026-03-31.html"


class TestGetReportsBucket:
    """Tests para _get_reports_bucket."""

    def test_returns_env_variable(self, monkeypatch):
        """Retorna el valor de la variable de entorno REPORTS_BUCKET."""
        monkeypatch.setenv("REPORTS_BUCKET", "mi-bucket-custom")
        assert _get_reports_bucket() == "mi-bucket-custom"

    def test_returns_default_when_not_set(self, monkeypatch):
        """Retorna el valor por defecto si no hay variable de entorno."""
        monkeypatch.delenv("REPORTS_BUCKET", raising=False)
        assert _get_reports_bucket() == "kiro-analytics-reports"


class TestStoreReports:
    """Tests para store_reports."""

    def test_stores_both_formats(self, s3_client, set_bucket_env):
        """Almacena HTML y CSV cuando output_format es 'both'."""
        html = "<html><body>Reporte</body></html>"
        csv_content = "col1,col2\nval1,val2\n"

        result = store_reports(
            html=html,
            csv_content=csv_content,
            period="weekly",
            start_date="2026-01-06",
            end_date="2026-01-12",
            output_format="both",
            s3_client=s3_client,
        )

        assert result.html_s3_key == "reports/kiro_report_weekly_2026-01-06_2026-01-12.html"
        assert result.csv_s3_key == "reports/kiro_report_weekly_2026-01-06_2026-01-12.csv"
        assert result.html_url is not None
        assert result.csv_url is not None
        assert result.generation_duration_seconds >= 0

    def test_stores_only_html(self, s3_client, set_bucket_env):
        """Almacena solo HTML cuando output_format es 'html'."""
        html = "<html><body>Solo HTML</body></html>"

        result = store_reports(
            html=html,
            csv_content="col1\nval1\n",
            period="daily",
            start_date="2026-02-10",
            end_date="2026-02-10",
            output_format="html",
            s3_client=s3_client,
        )

        assert result.html_s3_key == "reports/kiro_report_daily_2026-02-10_2026-02-10.html"
        assert result.html_url is not None
        assert result.csv_s3_key is None
        assert result.csv_url is None

    def test_stores_only_csv(self, s3_client, set_bucket_env):
        """Almacena solo CSV cuando output_format es 'csv'."""
        csv_content = "username,credits\njuan,100\n"

        result = store_reports(
            html="<html></html>",
            csv_content=csv_content,
            period="monthly",
            start_date="2026-03-01",
            end_date="2026-03-31",
            output_format="csv",
            s3_client=s3_client,
        )

        assert result.csv_s3_key == "reports/kiro_report_monthly_2026-03-01_2026-03-31.csv"
        assert result.csv_url is not None
        assert result.html_s3_key is None
        assert result.html_url is None

    def test_html_none_with_both_format(self, s3_client, set_bucket_env):
        """No almacena HTML si el contenido es None aunque format sea 'both'."""
        result = store_reports(
            html=None,
            csv_content="col1\nval1\n",
            period="daily",
            start_date="2026-01-01",
            end_date="2026-01-01",
            output_format="both",
            s3_client=s3_client,
        )

        assert result.html_s3_key is None
        assert result.html_url is None
        assert result.csv_s3_key is not None
        assert result.csv_url is not None

    def test_csv_none_with_both_format(self, s3_client, set_bucket_env):
        """No almacena CSV si el contenido es None aunque format sea 'both'."""
        result = store_reports(
            html="<html></html>",
            csv_content=None,
            period="daily",
            start_date="2026-01-01",
            end_date="2026-01-01",
            output_format="both",
            s3_client=s3_client,
        )

        assert result.html_s3_key is not None
        assert result.html_url is not None
        assert result.csv_s3_key is None
        assert result.csv_url is None

    def test_content_type_html(self, s3_client, set_bucket_env):
        """Verifica que el content-type del HTML es text/html."""
        store_reports(
            html="<html><body>Test</body></html>",
            csv_content=None,
            period="daily",
            start_date="2026-01-01",
            end_date="2026-01-01",
            output_format="html",
            s3_client=s3_client,
        )

        response = s3_client.get_object(
            Bucket=BUCKET,
            Key="reports/kiro_report_daily_2026-01-01_2026-01-01.html",
        )
        assert response["ContentType"] == "text/html"

    def test_content_type_csv(self, s3_client, set_bucket_env):
        """Verifica que el content-type del CSV es text/csv."""
        store_reports(
            html=None,
            csv_content="col1,col2\nval1,val2\n",
            period="daily",
            start_date="2026-01-01",
            end_date="2026-01-01",
            output_format="csv",
            s3_client=s3_client,
        )

        response = s3_client.get_object(
            Bucket=BUCKET,
            Key="reports/kiro_report_daily_2026-01-01_2026-01-01.csv",
        )
        assert response["ContentType"] == "text/csv"

    def test_uploaded_content_matches(self, s3_client, set_bucket_env):
        """Verifica que el contenido subido coincide con el original."""
        html = "<html><body>Contenido con acentos: análisis</body></html>"
        csv_content = "nombre,valor\nJosé,42\n"

        store_reports(
            html=html,
            csv_content=csv_content,
            period="weekly",
            start_date="2026-05-05",
            end_date="2026-05-11",
            output_format="both",
            s3_client=s3_client,
        )

        # Verificar HTML
        html_response = s3_client.get_object(
            Bucket=BUCKET,
            Key="reports/kiro_report_weekly_2026-05-05_2026-05-11.html",
        )
        assert html_response["Body"].read().decode("utf-8") == html

        # Verificar CSV
        csv_response = s3_client.get_object(
            Bucket=BUCKET,
            Key="reports/kiro_report_weekly_2026-05-05_2026-05-11.csv",
        )
        assert csv_response["Body"].read().decode("utf-8") == csv_content

    def test_error_raises_runtime_error(self, set_bucket_env):
        """Lanza RuntimeError si S3 falla (bucket inexistente)."""
        with mock_aws():
            client = boto3.client("s3", region_name="us-east-1")
            # No creamos el bucket para provocar error

            with pytest.raises(RuntimeError, match="Error al almacenar reporte en S3"):
                store_reports(
                    html="<html></html>",
                    csv_content=None,
                    period="daily",
                    start_date="2026-01-01",
                    end_date="2026-01-01",
                    output_format="html",
                    s3_client=client,
                )

    def test_presigned_url_contains_bucket_and_key(self, s3_client, set_bucket_env):
        """Las URLs pre-firmadas contienen el bucket y la clave del objeto."""
        result = store_reports(
            html="<html></html>",
            csv_content=None,
            period="daily",
            start_date="2026-06-15",
            end_date="2026-06-15",
            output_format="html",
            s3_client=s3_client,
        )

        assert BUCKET in result.html_url
        assert "kiro_report_daily_2026-06-15_2026-06-15.html" in result.html_url

    def test_generation_duration_recorded(self, s3_client, set_bucket_env):
        """Registra la duración de la generación."""
        result = store_reports(
            html="<html></html>",
            csv_content="a,b\n1,2\n",
            period="daily",
            start_date="2026-01-01",
            end_date="2026-01-01",
            output_format="both",
            s3_client=s3_client,
        )

        assert result.generation_duration_seconds >= 0
        assert isinstance(result.generation_duration_seconds, float)
