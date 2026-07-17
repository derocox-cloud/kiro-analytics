"""
Tests de integración para verificar el flujo completo del pipeline.

Verifica que src/pipeline.py conecta correctamente todos los componentes:
- Validación → recolección → procesamiento → análisis → reportes → publicación → notificación
- Manejo del flag ai_analysis para omitir análisis AI (Req 4.4)
- Degradación elegante cuando la publicación falla (Req 8.6)
"""
import boto3
import pytest
from moto import mock_aws

from src.pipeline import run_pipeline, PipelineResult


LOGS_BUCKET = "dev-logs-prompt-kiro-123456789012-us-east-1-an"
REPORTS_BUCKET = "kiro-analytics-reports"
SITE_BUCKET = "kiro-analytics-site"

ROSTER_CSV = (
    "Username,Display name,Status,Email,User ID\n"
    "jdoe,John Doe,Enabled,jdoe@test.com,user-001\n"
    "testuser,Test User,Enabled,test@test.com,user-002\n"
    "disabled,Disabled User,Disabled,disabled@test.com,user-003\n"
)


class TestPipelineValidation:
    """Tests de validación de entrada del pipeline."""

    def test_parametros_invalidos_rechazan_ejecucion(self):
        """Si los parámetros son inválidos, el pipeline falla en validación."""
        result = run_pipeline({"period": "invalid", "reference_date": "2026-01-15"})
        assert result.status == "FAILED"
        assert result.failure_stage == "validacion"
        assert "period" in result.error.lower()

    def test_fecha_invalida_rechaza_ejecucion(self):
        """Si la fecha no es válida, el pipeline falla en validación."""
        result = run_pipeline({"period": "daily", "reference_date": "not-a-date"})
        assert result.status == "FAILED"
        assert result.failure_stage == "validacion"
        assert "reference_date" in result.error.lower()

    def test_parametros_validos_pasan_validacion(self):
        """Si los parámetros son válidos, el pipeline pasa la etapa de validación."""
        result = run_pipeline(
            {"period": "daily", "reference_date": "2026-01-15"},
            s3_client=None,
        )
        # Falla en roster porque no hay S3, pero no en validación
        assert result.failure_stage != "validacion"


class TestPipelineFlowAIDisabled:
    """Tests del flujo completo con AI deshabilitado (Req 4.4)."""

    @mock_aws
    def test_flujo_completo_sin_ai(self):
        """El pipeline completa exitosamente con ai_analysis=False."""
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=LOGS_BUCKET)
        s3.create_bucket(Bucket=REPORTS_BUCKET)
        s3.create_bucket(Bucket=SITE_BUCKET)
        s3.put_object(Bucket=LOGS_BUCKET, Key="config/roster.csv", Body=ROSTER_CSV.encode())

        result = run_pipeline(
            event={
                "period": "daily",
                "reference_date": "2026-01-15",
                "ai_analysis": False,
                "output_format": "both",
            },
            s3_client=s3,
            roster_bucket=LOGS_BUCKET,
            roster_key="config/roster.csv",
            temp_bucket=LOGS_BUCKET,
            site_bucket=SITE_BUCKET,
        )

        assert result.status == "SUCCEEDED"
        assert result.ai_skipped is True
        assert result.ai_available is False
        assert result.period == "daily"
        assert result.reference_date == "2026-01-15"
        assert result.report_urls is not None
        assert "html" in result.report_urls
        assert "csv" in result.report_urls

    @mock_aws
    def test_flujo_completo_output_solo_html(self):
        """El pipeline genera solo HTML cuando output_format='html'."""
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=LOGS_BUCKET)
        s3.create_bucket(Bucket=REPORTS_BUCKET)
        s3.create_bucket(Bucket=SITE_BUCKET)
        s3.put_object(Bucket=LOGS_BUCKET, Key="config/roster.csv", Body=ROSTER_CSV.encode())

        result = run_pipeline(
            event={
                "period": "weekly",
                "reference_date": "2026-01-15",
                "ai_analysis": False,
                "output_format": "html",
            },
            s3_client=s3,
            roster_bucket=LOGS_BUCKET,
            roster_key="config/roster.csv",
            temp_bucket=LOGS_BUCKET,
            site_bucket=SITE_BUCKET,
        )

        assert result.status == "SUCCEEDED"
        assert result.report_urls is not None
        assert "html" in result.report_urls


class TestPipelineDegradation:
    """Tests de degradación elegante del pipeline."""

    @mock_aws
    def test_publicacion_falla_pipeline_continua(self):
        """Si la publicación falla, el pipeline continúa con indicador (Req 8.6)."""
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=LOGS_BUCKET)
        s3.create_bucket(Bucket=REPORTS_BUCKET)
        # NO crear bucket del sitio → publicación fallará
        s3.put_object(Bucket=LOGS_BUCKET, Key="config/roster.csv", Body=ROSTER_CSV.encode())

        result = run_pipeline(
            event={
                "period": "daily",
                "reference_date": "2026-01-15",
                "ai_analysis": False,
                "output_format": "html",
            },
            s3_client=s3,
            roster_bucket=LOGS_BUCKET,
            roster_key="config/roster.csv",
            temp_bucket=LOGS_BUCKET,
            site_bucket="nonexistent-bucket",
        )

        # Pipeline DEBE completar (status=SUCCEEDED) con indicador de fallo parcial
        assert result.status == "SUCCEEDED"
        assert result.publish_success is False
        assert result.report_urls is not None

    @mock_aws
    def test_pipeline_registra_duraciones_por_etapa(self):
        """El pipeline registra la duración de cada etapa ejecutada."""
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=LOGS_BUCKET)
        s3.create_bucket(Bucket=REPORTS_BUCKET)
        s3.create_bucket(Bucket=SITE_BUCKET)
        s3.put_object(Bucket=LOGS_BUCKET, Key="config/roster.csv", Body=ROSTER_CSV.encode())

        result = run_pipeline(
            event={
                "period": "monthly",
                "reference_date": "2026-01-15",
                "ai_analysis": False,
            },
            s3_client=s3,
            roster_bucket=LOGS_BUCKET,
            roster_key="config/roster.csv",
            temp_bucket=LOGS_BUCKET,
            site_bucket=SITE_BUCKET,
        )

        assert result.status == "SUCCEEDED"
        # Verificar que se registraron duraciones de las etapas principales
        assert "validacion" in result.stage_durations
        assert "lectura_roster" in result.stage_durations
        assert "recoleccion" in result.stage_durations
        assert "procesamiento" in result.stage_durations
        assert "generacion_reportes" in result.stage_durations
        assert "publicacion" in result.stage_durations
        assert "notificacion" in result.stage_durations
        # Análisis AI no debería estar porque se omitió
        assert "analisis_ai" not in result.stage_durations


class TestPipelineSiteIndex:
    """Tests de actualización de la página índice del sitio."""

    @mock_aws
    def test_publicacion_exitosa_actualiza_indice(self):
        """Cuando la publicación es exitosa, se actualiza index.html."""
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=LOGS_BUCKET)
        s3.create_bucket(Bucket=REPORTS_BUCKET)
        s3.create_bucket(Bucket=SITE_BUCKET)
        s3.put_object(Bucket=LOGS_BUCKET, Key="config/roster.csv", Body=ROSTER_CSV.encode())

        result = run_pipeline(
            event={
                "period": "daily",
                "reference_date": "2026-01-15",
                "ai_analysis": False,
                "output_format": "html",
            },
            s3_client=s3,
            roster_bucket=LOGS_BUCKET,
            roster_key="config/roster.csv",
            temp_bucket=LOGS_BUCKET,
            site_bucket=SITE_BUCKET,
        )

        assert result.status == "SUCCEEDED"
        assert result.publish_success is True

        # Verificar que index.html existe en el sitio
        site_objs = s3.list_objects_v2(Bucket=SITE_BUCKET)
        site_keys = [obj["Key"] for obj in site_objs.get("Contents", [])]
        assert "index.html" in site_keys
        assert "kiro_report_daily_2026-01-15_2026-01-15.html" in site_keys
