"""
Tests unitarios para el escritor de métricas en DynamoDB.

Usa moto para simular DynamoDB y verificar la persistencia correcta
de métricas de usuarios con clave compuesta (user_id + periodo).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from src.models import UserMetrics
from src.processors.dynamodb_writer import (
    _build_sort_key,
    _get_table_name,
    _metrics_to_item,
    persist_metrics,
)

# Nombre de tabla para tests
TEST_TABLE_NAME = "test-kiro-analytics-metrics"


def _create_test_table(dynamodb_resource):
    """Crea la tabla DynamoDB de prueba con el esquema esperado."""
    table = dynamodb_resource.create_table(
        TableName=TEST_TABLE_NAME,
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


def _make_user_metrics(
    user_id: str = "user-001",
    username: str = "jdoe",
    display_name: str = "John Doe",
    email: str = "jdoe@example.com",
    credits_used: float = 50.5,
    credits_monthly: float = 120.0,
    credits_pct: float = 12.0,
    conversations: int = 10,
    total_messages: int = 45,
    days_active: int = 5,
    clients_used: list | None = None,
    chat_messages_sent: int = 30,
    ai_code_lines: int = 200,
    inline_suggestions: int = 15,
    inline_accepted: int = 8,
    prompt_count: int = 25,
    prompt_categories: dict | None = None,
    intents: dict | None = None,
    models: dict | None = None,
) -> UserMetrics:
    """Crea un objeto UserMetrics de prueba con valores por defecto."""
    return UserMetrics(
        user_id=user_id,
        username=username,
        display_name=display_name,
        email=email,
        credits_used=credits_used,
        credits_monthly=credits_monthly,
        credits_pct=credits_pct,
        conversations=conversations,
        total_messages=total_messages,
        days_active=days_active,
        clients_used=clients_used if clients_used is not None else ["VSCode", "JetBrains"],
        chat_messages_sent=chat_messages_sent,
        ai_code_lines=ai_code_lines,
        inline_suggestions=inline_suggestions,
        inline_accepted=inline_accepted,
        prompt_count=prompt_count,
        prompt_categories=prompt_categories or {"Código": 10, "Testing": 5},
        intents=intents or {"chat": 15, "do": 8, "spec": 2, "total": 25},
        models=models or {"Claude Haiku": 20, "Claude Sonnet": 5},
    )


class TestBuildSortKey:
    """Tests para la construcción de la clave de ordenamiento."""

    def test_formato_daily(self):
        """Verifica formato correcto para periodo diario."""
        sk = _build_sort_key("daily", date(2026, 1, 15), date(2026, 1, 15))
        assert sk == "daily_2026-01-15_2026-01-15"

    def test_formato_weekly(self):
        """Verifica formato correcto para periodo semanal."""
        sk = _build_sort_key("weekly", date(2026, 1, 13), date(2026, 1, 19))
        assert sk == "weekly_2026-01-13_2026-01-19"

    def test_formato_monthly(self):
        """Verifica formato correcto para periodo mensual."""
        sk = _build_sort_key("monthly", date(2026, 3, 1), date(2026, 3, 31))
        assert sk == "monthly_2026-03-01_2026-03-31"


class TestMetricsToItem:
    """Tests para la conversión de UserMetrics a item de DynamoDB."""

    def test_campos_basicos(self):
        """Verifica que los campos básicos se mapean correctamente."""
        metrics = _make_user_metrics()
        item = _metrics_to_item(
            metrics, "weekly", date(2026, 1, 13), date(2026, 1, 19), "2026-01-20T10:00:00+00:00"
        )

        assert item["user_id"] == "user-001"
        assert item["periodo"] == "weekly_2026-01-13_2026-01-19"
        assert item["username"] == "jdoe"
        assert item["display_name"] == "John Doe"
        assert item["email"] == "jdoe@example.com"
        assert item["processed_at"] == "2026-01-20T10:00:00+00:00"

    def test_campos_numericos(self):
        """Verifica que los campos numéricos se convierten correctamente."""
        metrics = _make_user_metrics(credits_used=99.9, conversations=42)
        item = _metrics_to_item(
            metrics, "daily", date(2026, 1, 15), date(2026, 1, 15), "2026-01-16T07:00:00+00:00"
        )

        # credits se almacenan como string para precisión decimal
        assert item["credits_used"] == "99.9"
        assert item["conversations"] == 42

    def test_clients_used_con_elementos(self):
        """Verifica que clients_used se convierte a set cuando tiene elementos."""
        metrics = _make_user_metrics(clients_used=["VSCode", "JetBrains"])
        item = _metrics_to_item(
            metrics, "daily", date(2026, 1, 15), date(2026, 1, 15), "2026-01-16T07:00:00+00:00"
        )

        assert item["clients_used"] == {"VSCode", "JetBrains"}

    def test_clients_used_vacio(self):
        """Verifica que clients_used vacío se almacena como lista vacía."""
        metrics = _make_user_metrics(clients_used=[])
        item = _metrics_to_item(
            metrics, "daily", date(2026, 1, 15), date(2026, 1, 15), "2026-01-16T07:00:00+00:00"
        )

        assert item["clients_used"] == []

    def test_mapas_prompt_categories(self):
        """Verifica que prompt_categories se almacena como Map."""
        categories = {"Código": 15, "Infraestructura": 3, "Otros": 7}
        metrics = _make_user_metrics(prompt_categories=categories)
        item = _metrics_to_item(
            metrics, "daily", date(2026, 1, 15), date(2026, 1, 15), "2026-01-16T07:00:00+00:00"
        )

        assert item["prompt_categories"] == categories

    def test_mapas_vacios(self):
        """Verifica que diccionarios vacíos se manejan correctamente."""
        metrics = _make_user_metrics()
        # Asignar directamente diccionarios vacíos al objeto
        metrics.prompt_categories = {}
        metrics.intents = {}
        metrics.models = {}
        item = _metrics_to_item(
            metrics, "daily", date(2026, 1, 15), date(2026, 1, 15), "2026-01-16T07:00:00+00:00"
        )

        assert item["prompt_categories"] == {}
        assert item["intents"] == {}
        assert item["models"] == {}


@mock_aws
class TestPersistMetrics:
    """Tests de integración para persist_metrics con DynamoDB mock."""

    def test_persistir_una_metrica(self):
        """Verifica la persistencia de una sola métrica."""
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_test_table(dynamodb)

        metrics = [_make_user_metrics()]
        persist_metrics(
            metrics=metrics,
            period="daily",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 15),
            table_name=TEST_TABLE_NAME,
            dynamodb_resource=dynamodb,
        )

        # Verificar que el item se escribió correctamente
        response = table.get_item(
            Key={"user_id": "user-001", "periodo": "daily_2026-01-15_2026-01-15"}
        )
        item = response["Item"]

        assert item["user_id"] == "user-001"
        assert item["periodo"] == "daily_2026-01-15_2026-01-15"
        assert item["username"] == "jdoe"
        assert item["conversations"] == 10
        assert "processed_at" in item

    def test_persistir_multiples_metricas(self):
        """Verifica la persistencia de múltiples métricas."""
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_test_table(dynamodb)

        metrics = [
            _make_user_metrics(user_id="user-001", username="alice"),
            _make_user_metrics(user_id="user-002", username="bob"),
            _make_user_metrics(user_id="user-003", username="charlie"),
        ]

        persist_metrics(
            metrics=metrics,
            period="weekly",
            start_date=date(2026, 1, 13),
            end_date=date(2026, 1, 19),
            table_name=TEST_TABLE_NAME,
            dynamodb_resource=dynamodb,
        )

        # Verificar que se escribieron los 3 items
        response = table.scan()
        assert response["Count"] == 3

    def test_persistir_lista_vacia(self):
        """Verifica que una lista vacía no genera errores."""
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_test_table(dynamodb)

        # No debe lanzar excepción
        persist_metrics(
            metrics=[],
            period="daily",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 15),
            table_name=TEST_TABLE_NAME,
            dynamodb_resource=dynamodb,
        )

    def test_clave_compuesta_correcta(self):
        """Verifica que la clave compuesta PK+SK se forma correctamente."""
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_test_table(dynamodb)

        metrics = [_make_user_metrics(user_id="uid-abc-123")]
        persist_metrics(
            metrics=metrics,
            period="monthly",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 31),
            table_name=TEST_TABLE_NAME,
            dynamodb_resource=dynamodb,
        )

        response = table.get_item(
            Key={"user_id": "uid-abc-123", "periodo": "monthly_2026-03-01_2026-03-31"}
        )
        assert "Item" in response

    def test_timestamp_procesamiento_iso8601(self):
        """Verifica que processed_at tiene formato ISO 8601."""
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_test_table(dynamodb)

        metrics = [_make_user_metrics()]
        persist_metrics(
            metrics=metrics,
            period="daily",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 15),
            table_name=TEST_TABLE_NAME,
            dynamodb_resource=dynamodb,
        )

        response = table.get_item(
            Key={"user_id": "user-001", "periodo": "daily_2026-01-15_2026-01-15"}
        )
        processed_at = response["Item"]["processed_at"]

        # Verificar que es un timestamp ISO 8601 válido
        from datetime import datetime, timezone

        parsed = datetime.fromisoformat(processed_at)
        assert parsed.tzinfo is not None  # Debe tener timezone

    def test_clients_used_como_set(self):
        """Verifica que clients_used se almacena como StringSet en DynamoDB."""
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_test_table(dynamodb)

        metrics = [_make_user_metrics(clients_used=["VSCode", "JetBrains"])]
        persist_metrics(
            metrics=metrics,
            period="daily",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 15),
            table_name=TEST_TABLE_NAME,
            dynamodb_resource=dynamodb,
        )

        response = table.get_item(
            Key={"user_id": "user-001", "periodo": "daily_2026-01-15_2026-01-15"}
        )
        clients = response["Item"]["clients_used"]
        # DynamoDB devuelve sets como sets de Python con boto3 resource
        assert "VSCode" in clients
        assert "JetBrains" in clients

    def test_batch_mayor_a_25_items(self):
        """Verifica que se manejan correctamente más de 25 items (límite de batch)."""
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_test_table(dynamodb)

        # Crear 30 métricas para forzar múltiples lotes
        metrics = [
            _make_user_metrics(user_id=f"user-{i:03d}", username=f"user{i}")
            for i in range(30)
        ]

        persist_metrics(
            metrics=metrics,
            period="weekly",
            start_date=date(2026, 1, 13),
            end_date=date(2026, 1, 19),
            table_name=TEST_TABLE_NAME,
            dynamodb_resource=dynamodb,
        )

        response = table.scan()
        assert response["Count"] == 30

    def test_credits_como_decimal(self):
        """Verifica que los créditos se almacenan con precisión decimal."""
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_test_table(dynamodb)

        metrics = [_make_user_metrics(credits_used=99.99, credits_monthly=250.75)]
        persist_metrics(
            metrics=metrics,
            period="daily",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 15),
            table_name=TEST_TABLE_NAME,
            dynamodb_resource=dynamodb,
        )

        response = table.get_item(
            Key={"user_id": "user-001", "periodo": "daily_2026-01-15_2026-01-15"}
        )
        item = response["Item"]
        # Se almacenan como string para mantener precisión
        assert item["credits_used"] == "99.99"
        assert item["credits_monthly"] == "250.75"

    def test_sobrescritura_mismo_periodo(self):
        """Verifica que re-ejecutar para el mismo periodo sobrescribe los datos."""
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_test_table(dynamodb)

        # Primera escritura
        metrics_v1 = [_make_user_metrics(credits_used=50.0)]
        persist_metrics(
            metrics=metrics_v1,
            period="daily",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 15),
            table_name=TEST_TABLE_NAME,
            dynamodb_resource=dynamodb,
        )

        # Segunda escritura (misma clave, diferentes valores)
        metrics_v2 = [_make_user_metrics(credits_used=75.0)]
        persist_metrics(
            metrics=metrics_v2,
            period="daily",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 15),
            table_name=TEST_TABLE_NAME,
            dynamodb_resource=dynamodb,
        )

        response = table.get_item(
            Key={"user_id": "user-001", "periodo": "daily_2026-01-15_2026-01-15"}
        )
        # Debe tener el valor actualizado
        assert response["Item"]["credits_used"] == "75.0"

        # Solo debe haber 1 item (no duplicado)
        scan = table.scan()
        assert scan["Count"] == 1


class TestGetTableName:
    """Tests para la obtención del nombre de tabla."""

    def test_usa_variable_entorno(self, monkeypatch):
        """Verifica que usa la variable de entorno si está definida."""
        monkeypatch.setenv("DYNAMODB_TABLE_NAME", "mi-tabla-custom")
        assert _get_table_name() == "mi-tabla-custom"

    def test_usa_default_sin_variable(self, monkeypatch):
        """Verifica que usa el nombre por defecto si no hay variable de entorno."""
        monkeypatch.delenv("DYNAMODB_TABLE_NAME", raising=False)
        assert _get_table_name() == "kiro-analytics-metrics"
