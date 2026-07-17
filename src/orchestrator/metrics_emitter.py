"""
Emisor de métricas personalizadas a CloudWatch para el pipeline de analytics.

Emite métricas de rendimiento y volumen de cada ejecución del pipeline,
incluyendo duración total, duración por etapa, usuarios procesados
y tamaño de datos recolectados.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

import boto3

from src.models import ExecutionResult

logger = logging.getLogger(__name__)

# Namespace de métricas personalizadas en CloudWatch
METRICS_NAMESPACE = "KiroAnalytics/Pipeline"

# Máximo de métricas por llamada a put_metric_data (límite AWS)
MAX_METRICS_PER_CALL = 1000


def emit_pipeline_metrics(
    execution_result: ExecutionResult,
    cloudwatch_client=None,
) -> bool:
    """
    Emite métricas personalizadas de la ejecución del pipeline a CloudWatch.

    Métricas emitidas:
    - TotalDuration: Duración total de la ejecución en segundos.
    - StageDuration: Duración de cada etapa en segundos (una métrica por etapa).
    - UsersProcessed: Número de usuarios procesados (count).
    - DataCollectedSize: Tamaño total de datos recolectados (bytes).

    Todas las métricas incluyen la dimensión 'Period' con el periodo de ejecución.
    Las métricas de etapa incluyen adicionalmente la dimensión 'StageName'.

    Args:
        execution_result: Resultado de la ejecución del pipeline.
        cloudwatch_client: Cliente boto3 de CloudWatch (opcional, se crea si no se provee).

    Returns:
        True si las métricas se emitieron correctamente, False en caso de error.
    """
    if cloudwatch_client is None:
        cloudwatch_client = boto3.client("cloudwatch")

    timestamp = datetime.now(timezone.utc)
    period = execution_result.period

    metric_data: List[dict] = []

    # Métrica: Duración total en segundos
    metric_data.append({
        "MetricName": "TotalDuration",
        "Dimensions": [
            {"Name": "Period", "Value": period},
        ],
        "Timestamp": timestamp,
        "Value": execution_result.total_duration_seconds,
        "Unit": "Seconds",
    })

    # Métricas: Duración por etapa en segundos
    for stage_name, duration in execution_result.stage_durations.items():
        metric_data.append({
            "MetricName": "StageDuration",
            "Dimensions": [
                {"Name": "Period", "Value": period},
                {"Name": "StageName", "Value": stage_name},
            ],
            "Timestamp": timestamp,
            "Value": duration,
            "Unit": "Seconds",
        })

    # Métrica: Número de usuarios procesados
    metric_data.append({
        "MetricName": "UsersProcessed",
        "Dimensions": [
            {"Name": "Period", "Value": period},
        ],
        "Timestamp": timestamp,
        "Value": float(execution_result.users_processed),
        "Unit": "Count",
    })

    # Métrica: Tamaño de datos recolectados en bytes
    metric_data.append({
        "MetricName": "DataCollectedSize",
        "Dimensions": [
            {"Name": "Period", "Value": period},
        ],
        "Timestamp": timestamp,
        "Value": float(execution_result.data_size_bytes),
        "Unit": "Bytes",
    })

    # Enviar métricas agrupadas (respetar límite de 1000 por llamada)
    try:
        for i in range(0, len(metric_data), MAX_METRICS_PER_CALL):
            batch = metric_data[i:i + MAX_METRICS_PER_CALL]
            cloudwatch_client.put_metric_data(
                Namespace=METRICS_NAMESPACE,
                MetricData=batch,
            )

        logger.info(
            "Métricas emitidas a CloudWatch: %d métricas en namespace '%s'",
            len(metric_data),
            METRICS_NAMESPACE,
        )
        return True

    except Exception as e:
        logger.error(
            "Error al emitir métricas a CloudWatch: %s", str(e)
        )
        return False
