"""
Notificador del pipeline de analytics.

Envía notificaciones por SNS sobre el resultado de la ejecución del pipeline:
- Correo de éxito con resumen de métricas y URLs pre-firmadas de reportes.
- Correo de fallo con etapa fallida, mensaje de error y enlace a CloudWatch.

Si el envío falla, registra el error en CloudWatch sin afectar el estado
del pipeline (la notificación es best-effort).
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from src.models import ExecutionResult, NotificationResult

logger = logging.getLogger(__name__)

# ARN del tópico SNS (configurable por variable de entorno)
DEFAULT_SNS_TOPIC_ARN = ""

# Región AWS para construir enlace a CloudWatch
DEFAULT_REGION = "us-east-1"

# Máximo de destinatarios permitidos
MAX_RECIPIENTS = 10
MIN_RECIPIENTS = 1


def _get_sns_topic_arn() -> str:
    """Obtiene el ARN del tópico SNS desde la variable de entorno."""
    return os.environ.get("SNS_TOPIC_ARN", DEFAULT_SNS_TOPIC_ARN)


def _get_region() -> str:
    """Obtiene la región AWS desde la variable de entorno."""
    return os.environ.get("AWS_REGION", DEFAULT_REGION)


def _build_cloudwatch_logs_url(execution_id: str, region: str) -> str:
    """
    Construye el enlace a los logs de CloudWatch para una ejecución.

    Args:
        execution_id: Identificador de la ejecución del pipeline.
        region: Región AWS donde se ejecuta el pipeline.

    Returns:
        URL directa a CloudWatch Logs para la ejecución.
    """
    base_url = f"https://{region}.console.aws.amazon.com/cloudwatch/home"
    log_group = "/aws/stepfunctions/kiro-analytics-pipeline"
    return (
        f"{base_url}?region={region}#logsV2:log-groups/log-group/"
        f"{log_group}/log-events/{execution_id}"
    )


def _build_success_subject(period: str, reference_date: str) -> str:
    """
    Construye el asunto del correo de éxito.

    Args:
        period: Periodo procesado ("daily", "weekly", "monthly").
        reference_date: Fecha de referencia en formato YYYY-MM-DD.

    Returns:
        Asunto del correo de éxito.
    """
    period_labels = {
        "daily": "Diario",
        "weekly": "Semanal",
        "monthly": "Mensual",
    }
    label = period_labels.get(period, period)
    return f"✅ Reporte Kiro {label} - {reference_date}"


def _build_failure_subject(period: str, reference_date: str) -> str:
    """
    Construye el asunto del correo de fallo.

    Args:
        period: Periodo procesado ("daily", "weekly", "monthly").
        reference_date: Fecha de referencia en formato YYYY-MM-DD.

    Returns:
        Asunto del correo de fallo.
    """
    period_labels = {
        "daily": "Diario",
        "weekly": "Semanal",
        "monthly": "Mensual",
    }
    label = period_labels.get(period, period)
    return f"❌ Fallo Pipeline Kiro {label} - {reference_date}"


def _build_success_body(
    execution_result: ExecutionResult,
    report_urls: Optional[Dict[str, str]],
) -> str:
    """
    Construye el cuerpo del correo de éxito con resumen de la ejecución.

    Incluye: usuarios activos, créditos totales, tasa de adopción,
    duración total y URLs pre-firmadas de los reportes generados.

    Args:
        execution_result: Resultado de la ejecución del pipeline.
        report_urls: Diccionario con URLs pre-firmadas {"html": url, "csv": url}.

    Returns:
        Cuerpo del correo de éxito formateado.
    """
    users_processed = execution_result.users_processed
    duration = execution_result.total_duration_seconds

    body_lines = [
        "Reporte de Kiro Analytics generado exitosamente.",
        "",
        "📊 Resumen de la ejecución:",
        f"  • Periodo: {execution_result.period}",
        f"  • Fecha de referencia: {execution_result.reference_date}",
        f"  • Usuarios activos procesados: {users_processed}",
        f"  • Duración total: {duration:.1f} segundos",
        "",
    ]

    # Agregar URLs de reportes si están disponibles
    if report_urls:
        body_lines.append("📄 Reportes generados:")
        if report_urls.get("html"):
            body_lines.append(f"  • HTML: {report_urls['html']}")
        if report_urls.get("csv"):
            body_lines.append(f"  • CSV: {report_urls['csv']}")
        body_lines.append("")
        body_lines.append("Las URLs pre-firmadas tienen validez de 7 días.")
    else:
        body_lines.append("⚠️ No se generaron URLs de reportes.")

    body_lines.append("")
    body_lines.append("---")
    body_lines.append(f"Ejecución ID: {execution_result.execution_id}")
    body_lines.append(f"Timestamp: {execution_result.timestamp}")

    return "\n".join(body_lines)


def _build_failure_body(execution_result: ExecutionResult) -> str:
    """
    Construye el cuerpo del correo de fallo con detalles del error.

    Incluye: etapa fallida, mensaje de error y enlace a CloudWatch Logs.

    Args:
        execution_result: Resultado de la ejecución fallida del pipeline.

    Returns:
        Cuerpo del correo de fallo formateado.
    """
    region = _get_region()
    cloudwatch_url = _build_cloudwatch_logs_url(
        execution_result.execution_id, region
    )

    failure_stage = execution_result.failure_stage or "Desconocida"
    failure_message = execution_result.failure_message or "Sin mensaje de error"

    body_lines = [
        "⚠️ El pipeline de Kiro Analytics ha fallado.",
        "",
        "🔍 Detalles del fallo:",
        f"  • Periodo: {execution_result.period}",
        f"  • Fecha de referencia: {execution_result.reference_date}",
        f"  • Etapa fallida: {failure_stage}",
        f"  • Error: {failure_message}",
        f"  • Duración hasta el fallo: {execution_result.total_duration_seconds:.1f}s",
        "",
        "📋 Logs de CloudWatch:",
        f"  {cloudwatch_url}",
        "",
        "---",
        f"Ejecución ID: {execution_result.execution_id}",
        f"Timestamp: {execution_result.timestamp}",
    ]

    return "\n".join(body_lines)


def _validate_recipients(recipients: List[str]) -> Optional[str]:
    """
    Valida la lista de destinatarios.

    Args:
        recipients: Lista de direcciones de correo electrónico.

    Returns:
        Mensaje de error si la validación falla, None si es válida.
    """
    if not recipients:
        return "La lista de destinatarios está vacía"

    if len(recipients) < MIN_RECIPIENTS:
        return f"Se requiere al menos {MIN_RECIPIENTS} destinatario"

    if len(recipients) > MAX_RECIPIENTS:
        return f"Máximo {MAX_RECIPIENTS} destinatarios permitidos, se recibieron {len(recipients)}"

    return None


def _publish_to_sns(
    sns_client,
    topic_arn: str,
    subject: str,
    message: str,
) -> None:
    """
    Publica un mensaje en el tópico SNS.

    Args:
        sns_client: Cliente boto3 de SNS.
        topic_arn: ARN del tópico SNS destino.
        subject: Asunto del mensaje.
        message: Cuerpo del mensaje.

    Raises:
        ClientError: Si la publicación falla.
    """
    sns_client.publish(
        TopicArn=topic_arn,
        Subject=subject,
        Message=message,
    )


def notify(
    execution_result: ExecutionResult,
    report_urls: Optional[Dict[str, str]],
    recipients: List[str],
    sns_client=None,
) -> NotificationResult:
    """
    Envía notificación por SNS sobre el resultado de la ejecución del pipeline.

    Si la ejecución fue exitosa, envía correo con resumen de métricas y
    URLs pre-firmadas de reportes. Si falló, envía correo con la etapa
    fallida, mensaje de error y enlace a CloudWatch Logs.

    Si falla el envío, registra el error en CloudWatch sin afectar el
    estado del pipeline.

    Args:
        execution_result: Resultado de la ejecución del pipeline.
        report_urls: Diccionario con URLs pre-firmadas {"html": url, "csv": url}.
                     None si no se generaron reportes.
        recipients: Lista de 1-10 destinatarios de correo electrónico.
        sns_client: Cliente boto3 de SNS (opcional, se crea uno si no se provee).

    Returns:
        NotificationResult indicando éxito o fallo del envío.
    """
    # Validar destinatarios
    validation_error = _validate_recipients(recipients)
    if validation_error:
        logger.error(
            "Error de validación de destinatarios: %s", validation_error
        )
        return NotificationResult(success=False, error=validation_error)

    # Obtener configuración
    topic_arn = _get_sns_topic_arn()
    if not topic_arn:
        error_msg = "SNS_TOPIC_ARN no está configurado"
        logger.error(error_msg)
        return NotificationResult(success=False, error=error_msg)

    # Construir asunto y cuerpo según estado de la ejecución
    if execution_result.status == "SUCCEEDED":
        subject = _build_success_subject(
            execution_result.period, execution_result.reference_date
        )
        body = _build_success_body(execution_result, report_urls)
    else:
        subject = _build_failure_subject(
            execution_result.period, execution_result.reference_date
        )
        body = _build_failure_body(execution_result)

    # Crear cliente SNS si no se proporcionó uno
    if sns_client is None:
        sns_client = boto3.client("sns")

    # Enviar notificación - si falla, registrar en CloudWatch sin afectar pipeline
    try:
        _publish_to_sns(sns_client, topic_arn, subject, body)
        logger.info(
            "Notificación enviada exitosamente para ejecución %s (estado=%s)",
            execution_result.execution_id,
            execution_result.status,
        )
        return NotificationResult(success=True)

    except (ClientError, Exception) as e:
        error_msg = f"Error al enviar notificación SNS: {str(e)}"
        logger.error(error_msg)
        return NotificationResult(success=False, error=error_msg)


def lambda_handler(event: dict, context=None) -> dict:
    """Handler Lambda para Step Functions — envía notificación de éxito."""
    import os

    recipients = os.environ.get("NOTIFICATION_EMAILS", "").split(",")
    recipients = [r.strip() for r in recipients if r.strip()]

    params = event.get("validation", {}).get("Payload", {}).get("params", {})
    if not params:
        params = event.get("validation", {}).get("params", {})
    if not params:
        params = event

    reports = event.get("reports", {}).get("Payload", {})
    if not reports:
        reports = event.get("reports", {})

    report_urls = {}
    if reports.get("html_url"):
        report_urls["html"] = reports["html_url"]
    if reports.get("csv_url"):
        report_urls["csv"] = reports["csv_url"]

    # Extraer métricas de la ejecución del state
    processing = event.get("processing", {}).get("Payload", {})
    if not processing:
        processing = event.get("processing", {})
    users_processed = processing.get("users_processed", 0)
    duration = reports.get("duration_seconds", 0.0)

    execution_result = ExecutionResult(
        execution_id=event.get("execution_id", "manual"),
        status="SUCCEEDED",
        period=params.get("period", ""),
        reference_date=params.get("reference_date", ""),
        total_duration_seconds=duration,
        users_processed=users_processed,
        report_urls=report_urls or None,
    )

    result = notify(execution_result, report_urls or None, recipients)
    return {"success": result.success, "error": result.error or ""}


def failure_handler(event: dict, context=None) -> dict:
    """Handler Lambda para Step Functions — envía notificación de fallo."""
    import os

    recipients = os.environ.get("NOTIFICATION_EMAILS", "").split(",")
    recipients = [r.strip() for r in recipients if r.strip()]

    params = event.get("validation", {}).get("Payload", {}).get("params", {})
    if not params:
        params = event.get("validation", {}).get("params", {})
    if not params:
        params = event

    error_info = event.get("error", {})
    error_msg = ""
    if isinstance(error_info, dict):
        cause = error_info.get("Cause", "")
        error_msg = error_info.get("Error", "") + ": " + cause

    execution_result = ExecutionResult(
        execution_id=event.get("execution_id", "manual"),
        status="FAILED",
        period=params.get("period", ""),
        reference_date=params.get("reference_date", ""),
        total_duration_seconds=0.0,
        failure_message=error_msg,
    )

    result = notify(execution_result, None, recipients)
    return {"success": result.success, "error": result.error or ""}
