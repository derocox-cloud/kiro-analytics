"""
Tests de integración end-to-end del pipeline con moto.

Verifica el flujo completo del pipeline con datos sintéticos usando moto
para simular S3 y DynamoDB:
- Test end-to-end del pipeline con datos sintéticos (Req 1.1)
- Test de recolección paralela con S3 mock (Req 2.1)
- Test de persistencia en DynamoDB mock (Req 3.3)
- Test de generación de URLs pre-firmadas (Req 5.5)
"""
from __future__ import annotations

import gzip
import io
import json
import os
from datetime import date

import boto3
import pytest
from moto import mock_aws

from src.collectors.collector import collect
from src.collectors.sources import (
    ANALYTICS_PREFIX,
    LOGS_BUCKET,
    PROMPTS_PREFIX,
    USER_REPORT_PREFIX,
    get_source_configs,
)
from src.generators.report_storage import (
    PRESIGNED_URL_EXPIRATION,
    store_reports,
)
from src.models import CollectorConfig, CollectionResult, User, UserMetrics
from src.pipeline import run_pipeline
from src.processors.dynamodb_writer import persist_metrics


# =============================================================================
# Constantes de prueba
# =============================================================================

REPORTS_BUCKET = "kiro-analytics-reports"
SITE_BUCKET = "kiro-analytics-site"
DYNAMODB_TABLE = "kiro-analytics-metrics"
REGION = "us-east-1"

# Roster de prueba con usuarios habilitados y deshabilitados
ROSTER_CSV = (
    "Username,Display name,Status,Email,User ID\n"
    "jdoe,John Doe,Enabled,jdoe@test.com,user-001\n"
    "testuser,Test User,Enabled,test@test.com,user-002\n"
    "maria,Maria Garcia,Enabled,maria@test.com,user-003\n"
    "disabled,Disabled User,Disabled,disabled@test.com,user-004\n"
)

# Datos CSV de user_report sintéticos
USER_REPORT_CSV = (
    "UserId,Date,Credits_Used,Chat_Conversations,Total_Messages,"
    "Client_Type,Claude_messages\n"
    "user-001,2026-01-15,25.5,3,10,VSCode,8\n"
    "user-002,2026-01-15,10.0,2,5,JetBrains,4\n"
    "user-003,2026-01-15,5.0,1,2,VSCode,2\n"
    "user-004,2026-01-15,50.0,10,30,VSCode,25\n"
)

# Datos CSV de by_user_analytic sintéticos
ANALYTICS_CSV = (
    "UserId,Chat_MessagesSent,Chat_AICodeLines,"
    "Inline_SuggestionsCount,Inline_AcceptanceCount\n"
    "user-001,8,120,50,30\n"
    "user-002,4,60,25,15\n"
    "user-003,2,20,10,5\n"
)

# Roster como lista de objetos User para tests unitarios
TEST_ROSTER = [
    User(user_id="user-001", username="jdoe", display_name="John Doe",
         email="jdoe@test.com", status="Enabled"),
    User(user_id="user-002", username="testuser", display_name="Test User",
         email="test@test.com", status="Enabled"),
    User(user_id="user-003", username="maria", display_name="Maria Garcia",
         email="maria@test.com", status="Enabled"),
    User(user_id="user-004", username="disabled", display_name="Disabled User",
         email="disabled@test.com", status="Disabled"),
]


# =============================================================================
# Utilidades para generar datos sintéticos en S3
# =============================================================================

def _create_prompt_metadata(user_id: str, prompt: str) -> dict:
    """Crea un registro de prompt-metadata con estructura real."""
    return {
        "generateAssistantResponseEventRequest": {
            "userId": user_id,
            "prompt": prompt,
            "timeStamp": "2026-01-15T10:00:00Z",
            "modelId": "anthropic.claude-haiku-4-5",
            "chatTriggerType": "manual",
        },
        "generateAssistantResponseEventResponse": {
            "assistantResponse": "Respuesta generada",
        },
    }


def _upload_gzipped_json(s3_client, bucket: str, key: str, data: dict) -> None:
    """Sube un dict como JSON comprimido con gzip a S3."""
    json_bytes = json.dumps(data).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(json_bytes)
    buf.seek(0)
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.read())


def _setup_s3_with_synthetic_data(s3_client, reference_date: str = "2026-01-15"):
    """
    Configura S3 mock con datos sintéticos completos para un test e2e.

    Crea buckets y sube archivos CSV y JSON.gz con estructura real.
    """
    # Crear buckets necesarios
    s3_client.create_bucket(Bucket=LOGS_BUCKET)
    s3_client.create_bucket(Bucket=REPORTS_BUCKET)
    s3_client.create_bucket(Bucket=SITE_BUCKET)

    # Subir roster
    s3_client.put_object(
        Bucket=LOGS_BUCKET,
        Key="config/roster.csv",
        Body=ROSTER_CSV.encode("utf-8"),
    )

    # Construir prefijo de fecha (2026/01/15/)
    parts = reference_date.split("-")
    date_prefix = f"{parts[0]}/{parts[1]}/{parts[2]}/"

    # Subir user_report CSV
    user_report_key = f"{USER_REPORT_PREFIX}/{date_prefix}user_report.csv"
    s3_client.put_object(
        Bucket=LOGS_BUCKET,
        Key=user_report_key,
        Body=USER_REPORT_CSV.encode("utf-8"),
    )

    # Subir by_user_analytic CSV
    analytics_key = f"{ANALYTICS_PREFIX}/{date_prefix}analytics.csv"
    s3_client.put_object(
        Bucket=LOGS_BUCKET,
        Key=analytics_key,
        Body=ANALYTICS_CSV.encode("utf-8"),
    )

    # Subir prompt-metadata JSON.gz
    prompts_data = {
        "records": [
            _create_prompt_metadata("user-001", "Help me write a function to sort an array"),
            _create_prompt_metadata("user-001", "Fix this bug in my AWS Lambda code"),
            _create_prompt_metadata("user-002", "Create a SQL query for user analytics"),
            _create_prompt_metadata("user-003", "Write a test for my React component"),
        ]
    }
    prompts_key = f"{PROMPTS_PREFIX}/{date_prefix}prompts_001.json.gz"
    _upload_gzipped_json(s3_client, LOGS_BUCKET, prompts_key, prompts_data)


def _create_dynamodb_table(dynamodb_resource):
    """Crea la tabla DynamoDB con la estructura esperada por el pipeline."""
    table = dynamodb_resource.create_table(
        TableName=DYNAMODB_TABLE,
        KeySchema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "periodo", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "periodo", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


# =============================================================================
# Tests end-to-end del pipeline (Req 1.1)
# =============================================================================

class TestPipelineEndToEnd:
    """Tests end-to-end del pipeline completo con datos sintéticos."""

    @mock_aws
    def test_pipeline_e2e_flujo_completo_con_datos_sinteticos(self):
        """
        El pipeline ejecuta todas las etapas exitosamente con datos sintéticos.

        Valida el orden de ejecución: validación → roster → recolección →
        procesamiento → reportes → publicación → notificación (Req 1.1).
        """
        os.environ["REPORTS_BUCKET"] = REPORTS_BUCKET
        s3 = boto3.client("s3", region_name=REGION)
        _setup_s3_with_synthetic_data(s3)

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

        # Pipeline completó exitosamente
        assert result.status == "SUCCEEDED"
        assert result.period == "daily"
        assert result.reference_date == "2026-01-15"

        # Se procesaron usuarios (basado en prompts recolectados)
        assert result.users_processed >= 1

        # Se generaron reportes con URLs
        assert result.report_urls is not None
        assert "html" in result.report_urls
        assert "csv" in result.report_urls

        # URLs son cadenas válidas con contenido
        assert len(result.report_urls["html"]) > 0
        assert len(result.report_urls["csv"]) > 0

        # Todas las etapas registraron duración
        assert "validacion" in result.stage_durations
        assert "lectura_roster" in result.stage_durations
        assert "recoleccion" in result.stage_durations
        assert "procesamiento" in result.stage_durations
        assert "generacion_reportes" in result.stage_durations
        assert "publicacion" in result.stage_durations
        assert "notificacion" in result.stage_durations

        # Duración total es positiva
        assert result.duration_seconds > 0

    @mock_aws
    def test_pipeline_e2e_weekly_con_multiples_dias(self):
        """
        El pipeline procesa correctamente un periodo semanal con datos
        distribuidos en múltiples días. Completa exitosamente y genera
        reportes incluso cuando las fuentes retornan datos parciales.
        """
        os.environ["REPORTS_BUCKET"] = REPORTS_BUCKET
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=LOGS_BUCKET)
        s3.create_bucket(Bucket=REPORTS_BUCKET)
        s3.create_bucket(Bucket=SITE_BUCKET)

        # Subir roster
        s3.put_object(
            Bucket=LOGS_BUCKET,
            Key="config/roster.csv",
            Body=ROSTER_CSV.encode("utf-8"),
        )

        # Subir datos de prompts para múltiples días (estos sí se procesan
        # porque prompt-metadata tiene max_files_per_day=500)
        # El ref_date=2026-01-15 (miércoles) genera rango: lun 13 → dom 19
        for day in range(13, 20):
            date_prefix = f"2026/01/{day:02d}/"
            prompts_data = {
                "records": [
                    _create_prompt_metadata("user-001", f"Help me write code for day {day}"),
                    _create_prompt_metadata("user-002", f"Fix bug on day {day}"),
                ]
            }
            _upload_gzipped_json(
                s3, LOGS_BUCKET,
                f"{PROMPTS_PREFIX}/{date_prefix}prompts.json.gz",
                prompts_data,
            )

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
        assert result.period == "weekly"
        # Usuarios procesados (prompts se recolectan correctamente)
        assert result.users_processed >= 2
        assert result.report_urls is not None
        assert "html" in result.report_urls

    @mock_aws
    def test_pipeline_e2e_sin_datos_completa_exitosamente(self):
        """
        El pipeline completa exitosamente cuando no hay archivos de datos
        para el periodo, retornando resultado vacío sin error (Req 2.4).
        """
        os.environ["REPORTS_BUCKET"] = REPORTS_BUCKET
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=LOGS_BUCKET)
        s3.create_bucket(Bucket=REPORTS_BUCKET)
        s3.create_bucket(Bucket=SITE_BUCKET)

        # Solo subir roster, sin datos de actividad
        s3.put_object(
            Bucket=LOGS_BUCKET,
            Key="config/roster.csv",
            Body=ROSTER_CSV.encode("utf-8"),
        )

        result = run_pipeline(
            event={
                "period": "daily",
                "reference_date": "2026-01-15",
                "ai_analysis": False,
            },
            s3_client=s3,
            roster_bucket=LOGS_BUCKET,
            roster_key="config/roster.csv",
            temp_bucket=LOGS_BUCKET,
            site_bucket=SITE_BUCKET,
        )

        # El pipeline completa sin error
        assert result.status == "SUCCEEDED"


# =============================================================================
# Tests de recolección paralela con S3 mock (Req 2.1)
# =============================================================================

class TestRecoleccionParalelaS3:
    """Tests de recolección de datos desde las 3 fuentes S3."""

    @mock_aws
    def test_recoleccion_tres_fuentes_en_paralelo(self):
        """
        La recolección obtiene datos de las 3 fuentes (user_report,
        by_user_analytic, prompt-metadata) correctamente (Req 2.1).

        Nota: se usa max_files_per_day con valor alto para CSVs ya que
        el valor 0 del config actual se interpreta como "0 archivos" en la
        lógica del collector.
        """
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=LOGS_BUCKET)

        date_prefix = "2026/01/15/"

        # Subir archivos para cada fuente
        s3.put_object(
            Bucket=LOGS_BUCKET,
            Key=f"{USER_REPORT_PREFIX}/{date_prefix}report.csv",
            Body=USER_REPORT_CSV.encode("utf-8"),
        )
        s3.put_object(
            Bucket=LOGS_BUCKET,
            Key=f"{ANALYTICS_PREFIX}/{date_prefix}analytics.csv",
            Body=ANALYTICS_CSV.encode("utf-8"),
        )
        prompts_data = {
            "records": [
                _create_prompt_metadata("user-001", "Help me write a Python function"),
                _create_prompt_metadata("user-002", "Create a database migration"),
            ]
        }
        _upload_gzipped_json(
            s3, LOGS_BUCKET,
            f"{PROMPTS_PREFIX}/{date_prefix}prompts.json.gz",
            prompts_data,
        )

        # Configurar recolectores con max_files_per_day explícito
        # para evitar el comportamiento de max_files_per_day=0
        configs = {
            "user_report": CollectorConfig(
                source_type="user_report",
                s3_prefix=USER_REPORT_PREFIX,
                file_extension=".csv",
                max_files_per_day=1000,
            ),
            "by_user_analytic": CollectorConfig(
                source_type="by_user_analytic",
                s3_prefix=ANALYTICS_PREFIX,
                file_extension=".csv",
                max_files_per_day=1000,
            ),
            "prompt-metadata": CollectorConfig(
                source_type="prompt-metadata",
                s3_prefix=PROMPTS_PREFIX,
                file_extension=".json.gz",
                max_files_per_day=500,
            ),
        }

        start = date(2026, 1, 15)
        end = date(2026, 1, 15)
        execution_id = "test-exec-001"

        results = {}
        for source_name, config in configs.items():
            result = collect(
                config=config,
                roster=TEST_ROSTER,
                start_date=start,
                end_date=end,
                execution_id=execution_id,
                s3_client=s3,
                bucket=LOGS_BUCKET,
                temp_bucket=LOGS_BUCKET,
            )
            results[source_name] = result

        # Verificar que las 3 fuentes retornaron datos
        assert "user_report" in results
        assert "by_user_analytic" in results
        assert "prompt-metadata" in results

        # user_report: 3 registros (excluye user-004 disabled)
        assert len(results["user_report"].records) == 3
        # by_user_analytic: 3 registros
        assert len(results["by_user_analytic"].records) == 3
        # prompt-metadata: 2 registros (user-001 y user-002)
        assert len(results["prompt-metadata"].records) == 2

    @mock_aws
    def test_recoleccion_filtra_usuarios_deshabilitados(self):
        """
        La recolección solo incluye datos de usuarios con status 'Enabled',
        excluyendo usuarios deshabilitados (Req 2.5).
        """
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=LOGS_BUCKET)

        date_prefix = "2026/01/15/"
        # CSV que incluye un usuario deshabilitado
        csv_with_disabled = (
            "UserId,Date,Credits_Used,Chat_Conversations,Total_Messages,"
            "Client_Type,Claude_messages\n"
            "user-001,2026-01-15,25.5,3,10,VSCode,8\n"
            "user-004,2026-01-15,50.0,10,30,VSCode,25\n"
        )
        s3.put_object(
            Bucket=LOGS_BUCKET,
            Key=f"{USER_REPORT_PREFIX}/{date_prefix}report.csv",
            Body=csv_with_disabled.encode("utf-8"),
        )

        config = CollectorConfig(
            source_type="user_report",
            s3_prefix=USER_REPORT_PREFIX,
            file_extension=".csv",
            max_files_per_day=1000,
        )
        result = collect(
            config=config,
            roster=TEST_ROSTER,
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 15),
            execution_id="test-filter",
            s3_client=s3,
            bucket=LOGS_BUCKET,
            temp_bucket=LOGS_BUCKET,
        )

        # Solo user-001 (Enabled) se incluye, user-004 (Disabled) se excluye
        assert len(result.records) == 1
        assert result.records[0]["_normalized_user_id"] == "user-001"

    @mock_aws
    def test_recoleccion_sin_archivos_retorna_vacio(self):
        """
        Si no hay archivos para una fuente en el rango de fechas,
        retorna resultado vacío sin error (Req 2.4).
        """
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=LOGS_BUCKET)

        config = get_source_configs()["user_report"]
        result = collect(
            config=config,
            roster=TEST_ROSTER,
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 15),
            execution_id="test-empty",
            s3_client=s3,
            bucket=LOGS_BUCKET,
            temp_bucket=LOGS_BUCKET,
        )

        # Resultado vacío, sin errores
        assert result.records == []
        assert result.file_count == 0
        assert result.source_type == "user_report"

    @mock_aws
    def test_recoleccion_prompt_metadata_respeta_limite_diario(self):
        """
        La recolección de prompt-metadata respeta el límite de 500 archivos
        por día configurado en max_files_per_day.
        """
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=LOGS_BUCKET)

        date_prefix = "2026/01/15/"

        # Subir 5 archivos de prompts (usamos un límite bajo para la prueba)
        for i in range(5):
            prompts_data = {
                "records": [
                    _create_prompt_metadata("user-001", f"Prompt número {i}"),
                ]
            }
            _upload_gzipped_json(
                s3, LOGS_BUCKET,
                f"{PROMPTS_PREFIX}/{date_prefix}prompts_{i:03d}.json.gz",
                prompts_data,
            )

        # Usar config con max_files_per_day=3 para verificar que se respeta el límite
        config = CollectorConfig(
            source_type="prompt-metadata",
            s3_prefix=PROMPTS_PREFIX,
            file_extension=".json.gz",
            max_files_per_day=3,
        )

        result = collect(
            config=config,
            roster=TEST_ROSTER,
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 15),
            execution_id="test-limit",
            s3_client=s3,
            bucket=LOGS_BUCKET,
            temp_bucket=LOGS_BUCKET,
        )

        # Solo se procesan 3 archivos (el límite configurado)
        assert result.file_count == 3


# =============================================================================
# Tests de persistencia en DynamoDB mock (Req 3.3)
# =============================================================================

class TestPersistenciaDynamoDB:
    """Tests de persistencia de métricas en DynamoDB con moto."""

    @mock_aws
    def test_persist_metrics_escribe_en_dynamodb(self):
        """
        persist_metrics escribe las métricas en DynamoDB con clave
        compuesta user_id (PK) + periodo (SK) (Req 3.3).
        """
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        _create_dynamodb_table(dynamodb)

        metrics = [
            UserMetrics(
                user_id="user-001",
                username="jdoe",
                display_name="John Doe",
                email="jdoe@test.com",
                credits_used=25.5,
                credits_monthly=100.0,
                credits_pct=10.0,
                conversations=3,
                total_messages=10,
                days_active=5,
                clients_used=["VSCode"],
                chat_messages_sent=8,
                ai_code_lines=120,
                inline_suggestions=50,
                inline_accepted=30,
                prompt_count=15,
                prompt_categories={"Código": 10, "Testing": 5},
                intents={"chat": 5, "do": 8, "spec": 2},
                models={"Claude": 15},
            ),
            UserMetrics(
                user_id="user-002",
                username="testuser",
                display_name="Test User",
                email="test@test.com",
                credits_used=10.0,
                credits_monthly=50.0,
                credits_pct=5.0,
                conversations=2,
                total_messages=5,
                days_active=3,
                clients_used=["JetBrains"],
                chat_messages_sent=4,
                ai_code_lines=60,
                inline_suggestions=25,
                inline_accepted=15,
                prompt_count=8,
                prompt_categories={"Base de Datos": 5, "Infraestructura": 3},
                intents={"chat": 3, "do": 4, "spec": 1},
                models={"Claude": 8},
            ),
        ]

        persist_metrics(
            metrics=metrics,
            period="daily",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 15),
            table_name=DYNAMODB_TABLE,
            dynamodb_resource=dynamodb,
        )

        # Verificar que los items se escribieron correctamente
        table = dynamodb.Table(DYNAMODB_TABLE)
        response = table.scan()
        items = response["Items"]

        assert len(items) == 2

        # Verificar estructura de clave compuesta
        user_001_item = next(i for i in items if i["user_id"] == "user-001")
        assert user_001_item["periodo"] == "daily_2026-01-15_2026-01-15"
        assert user_001_item["username"] == "jdoe"
        assert user_001_item["email"] == "jdoe@test.com"

        user_002_item = next(i for i in items if i["user_id"] == "user-002")
        assert user_002_item["periodo"] == "daily_2026-01-15_2026-01-15"
        assert user_002_item["username"] == "testuser"

    @mock_aws
    def test_persist_metrics_formato_sk_correcto(self):
        """
        El SK de DynamoDB tiene formato '{period}_{start_date}_{end_date}'
        para diferentes periodos (Req 3.3).
        """
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        _create_dynamodb_table(dynamodb)

        metrics = [
            UserMetrics(
                user_id="user-001",
                username="jdoe",
                display_name="John Doe",
                email="jdoe@test.com",
                credits_used=25.5,
                credits_monthly=100.0,
                credits_pct=10.0,
                conversations=3,
                total_messages=10,
                days_active=5,
                clients_used=["VSCode"],
                chat_messages_sent=8,
                ai_code_lines=120,
                inline_suggestions=50,
                inline_accepted=30,
                prompt_count=15,
            ),
        ]

        # Periodo semanal
        persist_metrics(
            metrics=metrics,
            period="weekly",
            start_date=date(2026, 1, 13),
            end_date=date(2026, 1, 19),
            table_name=DYNAMODB_TABLE,
            dynamodb_resource=dynamodb,
        )

        table = dynamodb.Table(DYNAMODB_TABLE)
        response = table.get_item(
            Key={"user_id": "user-001", "periodo": "weekly_2026-01-13_2026-01-19"}
        )
        assert "Item" in response
        assert response["Item"]["periodo"] == "weekly_2026-01-13_2026-01-19"

    @mock_aws
    def test_persist_metrics_incluye_processed_at(self):
        """
        Cada item en DynamoDB incluye un campo processed_at con timestamp ISO 8601.
        """
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        _create_dynamodb_table(dynamodb)

        metrics = [
            UserMetrics(
                user_id="user-001",
                username="jdoe",
                display_name="John Doe",
                email="jdoe@test.com",
                credits_used=25.5,
                credits_monthly=100.0,
                credits_pct=10.0,
                conversations=3,
                total_messages=10,
                days_active=5,
                clients_used=[],
                chat_messages_sent=8,
                ai_code_lines=120,
                inline_suggestions=50,
                inline_accepted=30,
                prompt_count=15,
            ),
        ]

        persist_metrics(
            metrics=metrics,
            period="monthly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            table_name=DYNAMODB_TABLE,
            dynamodb_resource=dynamodb,
        )

        table = dynamodb.Table(DYNAMODB_TABLE)
        response = table.scan()
        item = response["Items"][0]

        # processed_at existe y tiene formato ISO 8601
        assert "processed_at" in item
        assert "T" in item["processed_at"]  # Formato ISO tiene T separador

    @mock_aws
    def test_persist_metrics_lista_vacia_no_escribe(self):
        """
        Si la lista de métricas está vacía, no se escribe nada en DynamoDB.
        """
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        _create_dynamodb_table(dynamodb)

        persist_metrics(
            metrics=[],
            period="daily",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 15),
            table_name=DYNAMODB_TABLE,
            dynamodb_resource=dynamodb,
        )

        table = dynamodb.Table(DYNAMODB_TABLE)
        response = table.scan()
        assert len(response["Items"]) == 0


# =============================================================================
# Tests de generación de URLs pre-firmadas (Req 5.5)
# =============================================================================

class TestURLsPreFirmadas:
    """Tests de generación de URLs pre-firmadas con validez de 7 días."""

    @mock_aws
    def test_store_reports_genera_url_prefirmada_html(self):
        """
        store_reports genera una URL pre-firmada para el reporte HTML (Req 5.5).
        """
        os.environ["REPORTS_BUCKET"] = REPORTS_BUCKET
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=REPORTS_BUCKET)

        html_content = "<html><body><h1>Reporte Kiro</h1></body></html>"

        result = store_reports(
            html=html_content,
            csv_content=None,
            period="daily",
            start_date="2026-01-15",
            end_date="2026-01-15",
            output_format="html",
            s3_client=s3,
        )

        # Se generó URL pre-firmada para HTML
        assert result.html_url is not None
        assert len(result.html_url) > 0
        assert "kiro_report_daily_2026-01-15_2026-01-15.html" in result.html_url
        assert result.html_s3_key == "kiro_report_daily_2026-01-15_2026-01-15.html"

        # No se generó URL para CSV (no se solicitó)
        assert result.csv_url is None

    @mock_aws
    def test_store_reports_genera_url_prefirmada_csv(self):
        """
        store_reports genera una URL pre-firmada para el reporte CSV (Req 5.5).
        """
        os.environ["REPORTS_BUCKET"] = REPORTS_BUCKET
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=REPORTS_BUCKET)

        csv_content = "username,credits_used\njdoe,25.5\ntestuser,10.0"

        result = store_reports(
            html=None,
            csv_content=csv_content,
            period="weekly",
            start_date="2026-01-13",
            end_date="2026-01-19",
            output_format="csv",
            s3_client=s3,
        )

        # Se generó URL pre-firmada para CSV
        assert result.csv_url is not None
        assert len(result.csv_url) > 0
        assert "kiro_report_weekly_2026-01-13_2026-01-19.csv" in result.csv_url
        assert result.csv_s3_key == "kiro_report_weekly_2026-01-13_2026-01-19.csv"

        # No se generó URL para HTML
        assert result.html_url is None

    @mock_aws
    def test_store_reports_genera_ambas_urls_formato_both(self):
        """
        Con output_format='both', se generan URLs pre-firmadas para
        ambos formatos (HTML y CSV) (Req 5.5).
        """
        os.environ["REPORTS_BUCKET"] = REPORTS_BUCKET
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=REPORTS_BUCKET)

        html_content = "<html><body><h1>Reporte</h1></body></html>"
        csv_content = "username,credits_used\njdoe,25.5"

        result = store_reports(
            html=html_content,
            csv_content=csv_content,
            period="monthly",
            start_date="2026-01-01",
            end_date="2026-01-31",
            output_format="both",
            s3_client=s3,
        )

        # Ambas URLs generadas
        assert result.html_url is not None
        assert result.csv_url is not None
        assert "kiro_report_monthly_2026-01-01_2026-01-31.html" in result.html_url
        assert "kiro_report_monthly_2026-01-01_2026-01-31.csv" in result.csv_url

    @mock_aws
    def test_url_prefirmada_validez_7_dias(self):
        """
        La constante PRESIGNED_URL_EXPIRATION es 604800 segundos (7 días)
        y la URL contiene el parámetro de expiración (Req 5.5).
        """
        # Verificar la constante de expiración (7 días en segundos)
        assert PRESIGNED_URL_EXPIRATION == 604800  # 7 * 24 * 60 * 60

        os.environ["REPORTS_BUCKET"] = REPORTS_BUCKET
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=REPORTS_BUCKET)

        result = store_reports(
            html="<html></html>",
            csv_content=None,
            period="daily",
            start_date="2026-01-15",
            end_date="2026-01-15",
            output_format="html",
            s3_client=s3,
        )

        # La URL pre-firmada debe contener parámetros de firma S3
        url = result.html_url
        assert "X-Amz-Expires" in url or "Expires" in url

    @mock_aws
    def test_nomenclatura_reporte_correcta(self):
        """
        Los reportes se almacenan con la nomenclatura estándar:
        kiro_report_{period}_{start_date}_{end_date}.{ext} (Req 5.3).
        """
        os.environ["REPORTS_BUCKET"] = REPORTS_BUCKET
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=REPORTS_BUCKET)

        result = store_reports(
            html="<html></html>",
            csv_content="col1,col2\nval1,val2",
            period="weekly",
            start_date="2026-01-13",
            end_date="2026-01-19",
            output_format="both",
            s3_client=s3,
        )

        # Verificar nomenclatura de claves S3
        assert result.html_s3_key == "kiro_report_weekly_2026-01-13_2026-01-19.html"
        assert result.csv_s3_key == "kiro_report_weekly_2026-01-13_2026-01-19.csv"

        # Verificar que los objetos existen en S3
        objs = s3.list_objects_v2(Bucket=REPORTS_BUCKET)
        keys = [o["Key"] for o in objs.get("Contents", [])]
        assert "kiro_report_weekly_2026-01-13_2026-01-19.html" in keys
        assert "kiro_report_weekly_2026-01-13_2026-01-19.csv" in keys
