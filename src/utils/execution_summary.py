"""Generador de resumen de ejecución para registro estructurado en CloudWatch."""
from __future__ import annotations

from datetime import datetime, timezone

from ..models import ExecutionResult


def build_execution_summary(execution_result: ExecutionResult) -> dict:
    """
    Genera un resumen JSON estructurado a partir del resultado de ejecución del pipeline.

    El resumen incluye los campos requeridos para registro en CloudWatch Logs:
    periodo, fecha_referencia, estado, duracion_total, duracion_por_etapa,
    usuarios_procesados, etapa_fallo (si aplica) y timestamp ISO 8601.

    Args:
        execution_result: Resultado completo de la ejecución del pipeline.

    Returns:
        Diccionario con el resumen estructurado listo para serialización JSON.
    """
    # Determinar timestamp: usar el del resultado si existe, o generar uno nuevo
    timestamp = execution_result.timestamp
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()

    return {
        "periodo": execution_result.period,
        "fecha_referencia": execution_result.reference_date,
        "estado": execution_result.status,
        "duracion_total": execution_result.total_duration_seconds,
        "duracion_por_etapa": dict(execution_result.stage_durations),
        "usuarios_procesados": execution_result.users_processed,
        "etapa_fallo": execution_result.failure_stage,
        "timestamp": timestamp,
    }


def lambda_handler(event: dict, context=None) -> dict:
    """Handler Lambda para Step Functions — emite métricas a CloudWatch."""
    import logging

    import boto3

    logger = logging.getLogger(__name__)

    cw_client = boto3.client("cloudwatch")

    # Determinar estado de la ejecución
    status = event.get("execution_status", {}).get("status", "SUCCEEDED")

    metrics = [
        {
            "MetricName": "PipelineExecution",
            "Value": 1,
            "Unit": "Count",
            "Dimensions": [
                {"Name": "Status", "Value": status},
            ],
        },
    ]

    try:
        cw_client.put_metric_data(
            Namespace="KiroAnalytics/Pipeline",
            MetricData=metrics,
        )
        logger.info("Métricas emitidas a CloudWatch: status=%s", status)
    except Exception as e:
        logger.warning("Error emitiendo métricas: %s", e)

    return {"emitted": True, "status": status}
