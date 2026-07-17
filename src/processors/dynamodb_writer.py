"""
Escritor de métricas procesadas en DynamoDB.

Persiste las métricas agregadas por usuario en una tabla DynamoDB
con clave compuesta: user_id (PK) + periodo (SK).
El formato del SK es: "{period}_{start_date}_{end_date}".
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError

from ..models import UserMetrics

logger = logging.getLogger(__name__)

# Nombre de la tabla DynamoDB (configurable por variable de entorno)
DEFAULT_TABLE_NAME = "kiro-analytics-metrics"


def _get_table_name() -> str:
    """Obtiene el nombre de la tabla DynamoDB desde variable de entorno o usa el default."""
    return os.environ.get("DYNAMODB_TABLE_NAME") or DEFAULT_TABLE_NAME


def _build_sort_key(period: str, start_date: date, end_date: date) -> str:
    """
    Construye la clave de ordenamiento (SK) para DynamoDB.

    Formato: "{period}_{start_date}_{end_date}" con fechas en YYYY-MM-DD.

    Args:
        period: Periodo de ejecución ("daily", "weekly", "monthly").
        start_date: Fecha de inicio del rango.
        end_date: Fecha de fin del rango.

    Returns:
        String con formato "{period}_{YYYY-MM-DD}_{YYYY-MM-DD}".
    """
    return f"{period}_{start_date.isoformat()}_{end_date.isoformat()}"


def _metrics_to_item(
    metrics: UserMetrics,
    period: str,
    start_date: date,
    end_date: date,
    processed_at: str,
) -> Dict[str, Any]:
    """
    Convierte un objeto UserMetrics a un item de DynamoDB.

    Maneja las conversiones de tipos:
    - Listas vacías se almacenan como listas vacías (DynamoDB las soporta)
    - Diccionarios se almacenan como Map
    - Sets vacíos no se envían (DynamoDB no permite sets vacíos)

    Args:
        metrics: Métricas del usuario a persistir.
        period: Periodo de ejecución.
        start_date: Fecha de inicio del rango.
        end_date: Fecha de fin del rango.
        processed_at: Timestamp ISO 8601 de procesamiento.

    Returns:
        Diccionario con el item listo para DynamoDB.
    """
    sort_key = _build_sort_key(period, start_date, end_date)

    item: Dict[str, Any] = {
        "user_id": metrics.user_id,
        "periodo": sort_key,
        "username": metrics.username,
        "display_name": metrics.display_name,
        "email": metrics.email,
        "credits_used": str(metrics.credits_used),
        "credits_monthly": str(metrics.credits_monthly),
        "credits_pct": str(metrics.credits_pct),
        "conversations": metrics.conversations,
        "total_messages": metrics.total_messages,
        "days_active": metrics.days_active,
        "chat_messages_sent": metrics.chat_messages_sent,
        "ai_code_lines": metrics.ai_code_lines,
        "inline_suggestions": metrics.inline_suggestions,
        "inline_accepted": metrics.inline_accepted,
        "prompt_count": metrics.prompt_count,
        "prompt_categories": metrics.prompt_categories or {},
        "intents": metrics.intents or {},
        "models": metrics.models or {},
        "processed_at": processed_at,
    }

    # clients_used: usar StringSet si hay elementos, omitir si está vacío
    if metrics.clients_used:
        item["clients_used"] = set(metrics.clients_used)
    else:
        item["clients_used"] = []

    return item


def persist_metrics(
    metrics: List[UserMetrics],
    period: str,
    start_date: date,
    end_date: date,
    table_name: str | None = None,
    dynamodb_resource: Any = None,
) -> None:
    """
    Persiste métricas de usuarios en DynamoDB usando batch_write_item.

    Escribe todas las métricas en la tabla DynamoDB con clave compuesta:
    - PK: user_id
    - SK: "{period}_{start_date}_{end_date}"

    Incluye un campo processed_at con el timestamp ISO 8601 del momento
    de procesamiento.

    Args:
        metrics: Lista de métricas de usuarios a persistir.
        period: Periodo de ejecución ("daily", "weekly", "monthly").
        start_date: Fecha de inicio del rango.
        end_date: Fecha de fin del rango.
        table_name: Nombre de la tabla (opcional, usa variable de entorno o default).
        dynamodb_resource: Recurso DynamoDB de boto3 (opcional, para testing).

    Raises:
        ClientError: Si falla la escritura en DynamoDB después de procesar los lotes.
    """
    if not metrics:
        logger.info("No hay métricas para persistir en DynamoDB.")
        return

    # Determinar nombre de tabla
    resolved_table_name = table_name or _get_table_name()

    # Crear recurso DynamoDB si no se proporcionó
    if dynamodb_resource is None:
        dynamodb_resource = boto3.resource("dynamodb")

    table = dynamodb_resource.Table(resolved_table_name)

    # Timestamp de procesamiento en ISO 8601 UTC
    processed_at = datetime.now(timezone.utc).isoformat()

    # Escribir en lotes de 25 (límite de batch_write_item de DynamoDB)
    batch_size = 25
    total_written = 0
    errors: List[str] = []

    for i in range(0, len(metrics), batch_size):
        batch = metrics[i:i + batch_size]

        try:
            with table.batch_writer() as writer:
                for m in batch:
                    item = _metrics_to_item(m, period, start_date, end_date, processed_at)
                    writer.put_item(Item=item)

            total_written += len(batch)
        except ClientError as e:
            error_msg = (
                f"Error escribiendo lote {i // batch_size + 1} en DynamoDB: "
                f"{e.response['Error']['Message']}"
            )
            logger.error(error_msg)
            errors.append(error_msg)
            raise

    logger.info(
        "Persistencia en DynamoDB completada: %d métricas escritas en tabla '%s'.",
        total_written,
        resolved_table_name,
    )
