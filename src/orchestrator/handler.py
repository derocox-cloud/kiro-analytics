"""
Handler principal del orquestador del pipeline de analytics.

Coordina la ejecución completa del pipeline en el orden:
validación → recolección paralela → procesamiento → análisis AI (condicional)
→ generación de reportes → publicación → notificación.

Implementa verificación de ejecución duplicada y emite evento de completación
a EventBridge al finalizar exitosamente.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from src.analyzers.ai_analyzer import analyze_prompts
from src.collectors.collector import collect
from src.collectors.sources import get_source_configs, read_roster_from_s3, LOGS_BUCKET
from src.generators.csv_generator import generate_csv
from src.generators.html_generator import generate_html
from src.generators.index_generator import generate_index
from src.generators.report_storage import store_reports
from src.generators.site_publisher import publish_report
from src.models import (
    CollectionResult,
    ExecutionResult,
    ReportMetadata,
)
from src.notifiers.notifier import notify
from src.processors.metrics_processor import process_metrics
from src.utils.date_utils import get_date_range
from src.utils.execution_summary import build_execution_summary
from src.validators.input_validator import validate_input

logger = logging.getLogger(__name__)

# Nombre del bus de EventBridge (configurable por variable de entorno)
EVENTBRIDGE_BUS_NAME = os.environ.get("EVENTBRIDGE_BUS_NAME", "default")

# Nombre del bucket de reportes para publicación web
REPORTS_SITE_BUCKET = os.environ.get("REPORTS_SITE_BUCKET", "kiro-analytics-site")

# Nombre del bucket temporal para datos intermedios
TEMP_BUCKET = os.environ.get("TEMP_BUCKET", "kiro-analytics-temp")

# Bucket del roster de usuarios
ROSTER_BUCKET = os.environ.get("ROSTER_BUCKET", LOGS_BUCKET)
ROSTER_KEY = os.environ.get("ROSTER_KEY", "config/kiro-users-dev.csv")

# Lista de destinatarios de notificación (separados por coma)
NOTIFICATION_RECIPIENTS = os.environ.get("NOTIFICATION_RECIPIENTS", "")

# Tabla DynamoDB para rastrear ejecuciones activas
EXECUTIONS_TABLE = os.environ.get("EXECUTIONS_TABLE", "kiro-analytics-executions")

# Fuente del evento emitido a EventBridge
EVENT_SOURCE = "kiro.analytics.pipeline"

# Tipo de detalle del evento de completación
EVENT_DETAIL_TYPE = "PipelineExecutionCompleted"


def _generate_execution_id() -> str:
    """Genera un identificador único para la ejecución del pipeline."""
    return str(uuid.uuid4())


def _check_duplicate_execution(
    dynamodb_client,
    period: str,
    reference_date: str,
) -> Optional[str]:
    """
    Verifica si existe una ejecución activa para el mismo periodo y fecha.

    Consulta la tabla de ejecuciones activas en DynamoDB. Si encuentra una
    ejecución con status 'IN_PROGRESS' para el mismo periodo y fecha,
    retorna el ID de la ejecución duplicada.

    Args:
        dynamodb_client: Cliente boto3 de DynamoDB.
        period: Periodo de la ejecución ("daily", "weekly", "monthly").
        reference_date: Fecha de referencia en formato YYYY-MM-DD.

    Returns:
        ID de la ejecución duplicada activa, o None si no hay duplicados.
    """
    execution_key = f"{period}_{reference_date}"

    try:
        response = dynamodb_client.get_item(
            TableName=EXECUTIONS_TABLE,
            Key={
                "execution_key": {"S": execution_key},
            },
        )

        item = response.get("Item")
        if item and item.get("status", {}).get("S") == "IN_PROGRESS":
            return item.get("execution_id", {}).get("S", "desconocido")

    except ClientError as e:
        # Si la tabla no existe o hay error de permisos, continuar sin bloquear
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "ResourceNotFoundException":
            logger.warning(
                "Tabla de ejecuciones '%s' no encontrada. "
                "Continuando sin verificación de duplicados.",
                EXECUTIONS_TABLE,
            )
            return None
        logger.warning(
            "Error consultando ejecuciones activas: %s. "
            "Continuando sin verificación de duplicados.",
            str(e),
        )

    return None


def _register_execution(
    dynamodb_client,
    execution_id: str,
    period: str,
    reference_date: str,
) -> None:
    """
    Registra una nueva ejecución como activa en DynamoDB.

    Args:
        dynamodb_client: Cliente boto3 de DynamoDB.
        execution_id: Identificador único de la ejecución.
        period: Periodo de la ejecución.
        reference_date: Fecha de referencia.
    """
    execution_key = f"{period}_{reference_date}"
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        dynamodb_client.put_item(
            TableName=EXECUTIONS_TABLE,
            Item={
                "execution_key": {"S": execution_key},
                "execution_id": {"S": execution_id},
                "period": {"S": period},
                "reference_date": {"S": reference_date},
                "status": {"S": "IN_PROGRESS"},
                "started_at": {"S": timestamp},
            },
        )
    except ClientError as e:
        logger.warning(
            "No se pudo registrar ejecución en DynamoDB: %s", str(e)
        )


def _update_execution_status(
    dynamodb_client,
    period: str,
    reference_date: str,
    status: str,
) -> None:
    """
    Actualiza el status de una ejecución en DynamoDB.

    Args:
        dynamodb_client: Cliente boto3 de DynamoDB.
        period: Periodo de la ejecución.
        reference_date: Fecha de referencia.
        status: Nuevo status ("SUCCEEDED" o "FAILED").
    """
    execution_key = f"{period}_{reference_date}"
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        dynamodb_client.update_item(
            TableName=EXECUTIONS_TABLE,
            Key={"execution_key": {"S": execution_key}},
            UpdateExpression="SET #s = :status, finished_at = :ts",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": {"S": status},
                ":ts": {"S": timestamp},
            },
        )
    except ClientError as e:
        logger.warning(
            "No se pudo actualizar status de ejecución: %s", str(e)
        )


def _collect_parallel(
    roster,
    start_date: date,
    end_date: date,
    execution_id: str,
    s3_client,
) -> Dict[str, CollectionResult]:
    """
    Ejecuta la recolección de datos de las tres fuentes en paralelo.

    Args:
        roster: Lista de usuarios del roster.
        start_date: Fecha de inicio del rango.
        end_date: Fecha de fin del rango.
        execution_id: Identificador de la ejecución.
        s3_client: Cliente boto3 de S3.

    Returns:
        Diccionario {source_type: CollectionResult} con resultados de cada fuente.

    Raises:
        RuntimeError: Si alguna de las recolecciones paralelas falla.
    """
    source_configs = get_source_configs()
    results: Dict[str, CollectionResult] = {}

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        for source_name, config in source_configs.items():
            future = executor.submit(
                collect,
                config=config,
                roster=roster,
                start_date=start_date,
                end_date=end_date,
                execution_id=execution_id,
                s3_client=s3_client,
                bucket=LOGS_BUCKET,
                temp_bucket=TEMP_BUCKET,
            )
            futures[future] = source_name

        for future in as_completed(futures):
            source_name = futures[future]
            try:
                result = future.result()
                results[source_name] = result
            except Exception as e:
                # Si una Lambda paralela falla, marcar toda la etapa como fallida
                raise RuntimeError(
                    f"Fallo en recolección de '{source_name}': {str(e)}"
                ) from e

    return results


def _emit_completion_event(
    events_client,
    period: str,
    reference_date: str,
    report_paths: Dict[str, str],
) -> None:
    """
    Emite un evento de completación a EventBridge.

    El evento incluye el periodo procesado, la fecha de referencia
    y las rutas S3 de los reportes generados.

    Args:
        events_client: Cliente boto3 de EventBridge.
        period: Periodo procesado ("daily", "weekly", "monthly").
        reference_date: Fecha de referencia en formato YYYY-MM-DD.
        report_paths: Diccionario con rutas S3 de reportes {"html": key, "csv": key}.
    """
    detail = {
        "period": period,
        "reference_date": reference_date,
        "report_paths": report_paths,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        events_client.put_events(
            Entries=[
                {
                    "Source": EVENT_SOURCE,
                    "DetailType": EVENT_DETAIL_TYPE,
                    "Detail": json.dumps(detail),
                    "EventBusName": EVENTBRIDGE_BUS_NAME,
                }
            ]
        )
        logger.info(
            "Evento de completación emitido a EventBridge: period=%s, date=%s",
            period,
            reference_date,
        )
    except ClientError as e:
        logger.error(
            "Error al emitir evento a EventBridge: %s", str(e)
        )


def _get_notification_recipients() -> List[str]:
    """Obtiene la lista de destinatarios de notificación desde variable de entorno."""
    raw = NOTIFICATION_RECIPIENTS.strip()
    if not raw:
        return []
    return [email.strip() for email in raw.split(",") if email.strip()]


def _list_existing_reports(s3_client, bucket: str) -> List[ReportMetadata]:
    """
    Lista los reportes HTML existentes en el bucket del sitio para actualizar el índice.

    Args:
        s3_client: Cliente boto3 de S3.
        bucket: Nombre del bucket del sitio de reportes.

    Returns:
        Lista de metadatos de reportes existentes.
    """
    reports: List[ReportMetadata] = []

    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(
            Bucket=bucket,
            Prefix="kiro_report_",
        )

        for page in page_iterator:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(".html"):
                    continue

                # Parsear metadata del nombre del archivo
                # Formato: kiro_report_{period}_{start}_{end}.html
                filename = key.split("/")[-1]
                parts = filename.replace(".html", "").split("_")
                # kiro_report_daily_2026-01-15_2026-01-15
                if len(parts) >= 5:
                    period = parts[2]
                    start_date = parts[3]
                    end_date = parts[4]
                    last_modified = obj.get("LastModified", "")
                    generated_at = (
                        last_modified.isoformat()
                        if hasattr(last_modified, "isoformat")
                        else str(last_modified)
                    )

                    reports.append(
                        ReportMetadata(
                            filename=filename,
                            period=period,
                            start_date=start_date,
                            end_date=end_date,
                            generated_at=generated_at,
                            s3_key=key,
                        )
                    )

    except ClientError as e:
        logger.warning("Error listando reportes existentes: %s", str(e))

    return reports


def handler(event: dict, context=None) -> dict:
    """
    Handler principal del orquestador del pipeline de analytics.

    Coordina la ejecución completa del pipeline:
    1. Validación de parámetros de entrada
    2. Verificación de ejecución duplicada
    3. Recolección paralela de datos (user_report, by_user_analytic, prompt-metadata)
    4. Procesamiento y agregación de métricas
    5. Análisis AI con Bedrock (condicional según flag ai_analysis)
    6. Generación de reportes (HTML y/o CSV)
    7. Publicación en sitio web y actualización de índice
    8. Notificación de resultado

    Al completar exitosamente, emite un evento de completación a EventBridge.

    Args:
        event: Diccionario con parámetros del pipeline:
            - period: "daily" | "weekly" | "monthly"
            - reference_date: "YYYY-MM-DD"
            - ai_analysis: bool (default True)
            - output_format: "html" | "csv" | "both" (default "both")
        context: Contexto Lambda (opcional).

    Returns:
        Diccionario con el resultado de la ejecución:
            - execution_id: Identificador único de la ejecución
            - status: "SUCCEEDED" o "FAILED"
            - period: Periodo procesado
            - reference_date: Fecha de referencia
            - report_urls: URLs pre-firmadas de los reportes (si exitoso)
            - error: Mensaje de error (si falló)
    """
    execution_id = _generate_execution_id()
    start_time = time.time()
    stage_durations: Dict[str, float] = {}

    logger.info(
        "Iniciando ejecución del pipeline. ID: %s, Evento: %s",
        execution_id,
        json.dumps(event, default=str),
    )

    # --- Etapa 1: Validación de entrada ---
    stage_start = time.time()
    validation_result = validate_input(event)
    stage_durations["validacion"] = time.time() - stage_start

    if not validation_result.valid:
        logger.error(
            "Validación fallida: %s", validation_result.error
        )
        return {
            "execution_id": execution_id,
            "status": "FAILED",
            "error": validation_result.error,
            "stage": "validacion",
        }

    params = validation_result.params
    period = params.period
    reference_date = params.reference_date
    ai_analysis_enabled = params.ai_analysis
    output_format = params.output_format

    # --- Etapa 2: Verificación de ejecución duplicada ---
    stage_start = time.time()
    dynamodb_client = boto3.client("dynamodb")

    duplicate_id = _check_duplicate_execution(
        dynamodb_client, period, reference_date
    )
    stage_durations["verificacion_duplicados"] = time.time() - stage_start

    if duplicate_id:
        error_msg = (
            f"Ejecución duplicada: ya existe una ejecución activa para "
            f"period='{period}', reference_date='{reference_date}' "
            f"(ejecución ID: {duplicate_id})."
        )
        logger.error(error_msg)
        return {
            "execution_id": execution_id,
            "status": "FAILED",
            "error": error_msg,
            "stage": "verificacion_duplicados",
        }

    # Registrar esta ejecución como activa
    _register_execution(dynamodb_client, execution_id, period, reference_date)

    # Calcular rango de fechas
    ref_date = date.fromisoformat(reference_date)
    start_date, end_date = get_date_range(period, ref_date)

    s3_client = boto3.client("s3")

    try:
        # --- Etapa 3: Lectura de roster ---
        stage_start = time.time()
        roster = read_roster_from_s3(s3_client, ROSTER_BUCKET, ROSTER_KEY)
        stage_durations["lectura_roster"] = time.time() - stage_start

        logger.info("Roster cargado: %d usuarios", len(roster))

        # --- Etapa 4: Recolección paralela ---
        stage_start = time.time()
        raw_data = _collect_parallel(
            roster=roster,
            start_date=start_date,
            end_date=end_date,
            execution_id=execution_id,
            s3_client=s3_client,
        )
        stage_durations["recoleccion"] = time.time() - stage_start

        total_data_size = sum(
            r.data_size_bytes for r in raw_data.values()
        )
        logger.info(
            "Recolección completada: %d fuentes, %d bytes totales",
            len(raw_data),
            total_data_size,
        )

        # --- Etapa 5: Procesamiento de métricas ---
        stage_start = time.time()
        processing_result = process_metrics(
            raw_data=raw_data,
            roster=roster,
            period=period,
            start_date=start_date,
            end_date=end_date,
        )
        stage_durations["procesamiento"] = time.time() - stage_start

        logger.info(
            "Procesamiento completado: %d usuarios activos, %d inactivos",
            processing_result.total_users_processed,
            len(processing_result.inactive_users),
        )

        # --- Etapa 6: Análisis AI (condicional) ---
        ai_result = None
        if ai_analysis_enabled:
            stage_start = time.time()

            # Construir diccionario de prompts por usuario para el analizador
            prompts_by_user: Dict[str, List[str]] = {}
            prompt_records = raw_data.get(
                "prompt-metadata", CollectionResult(source_type="prompt-metadata")
            ).records

            for rec in prompt_records:
                uid = rec.get("_normalized_user_id", "")
                if not uid:
                    continue
                req = rec.get("generateAssistantResponseEventRequest", {})
                prompt_text = req.get("prompt", "")
                if prompt_text and len(prompt_text.strip()) > 5:
                    if uid not in prompts_by_user:
                        prompts_by_user[uid] = []
                    prompts_by_user[uid].append(prompt_text)

            # Construir diccionario de usuarios
            users_dict = {u.user_id: u for u in roster if u.status == "Enabled"}

            ai_result = analyze_prompts(prompts_by_user, users_dict)
            stage_durations["analisis_ai"] = time.time() - stage_start

            if ai_result.available:
                logger.info(
                    "Análisis AI completado: %d tokens usados",
                    ai_result.tokens_used,
                )
            else:
                logger.warning(
                    "Análisis AI no disponible: %s",
                    ai_result.error_message,
                )
        else:
            logger.info("Análisis AI omitido (flag deshabilitado).")

        # --- Etapa 7: Generación de reportes ---
        stage_start = time.time()

        start_date_str = start_date.isoformat()
        end_date_str = end_date.isoformat()

        html_content = None
        csv_content = None

        if output_format in ("html", "both"):
            html_content = generate_html(
                metrics=processing_result,
                ai_analysis=ai_result,
                period=period,
                start_date=start_date_str,
                end_date=end_date_str,
            )

        if output_format in ("csv", "both"):
            csv_content = generate_csv(
                metrics=processing_result,
                period=period,
                start_date=start_date_str,
                end_date=end_date_str,
            )

        # Almacenar en S3 y generar URLs pre-firmadas
        report_result = store_reports(
            html=html_content,
            csv_content=csv_content,
            period=period,
            start_date=start_date_str,
            end_date=end_date_str,
            output_format=output_format,
            s3_client=s3_client,
        )
        stage_durations["generacion_reportes"] = time.time() - stage_start

        logger.info(
            "Reportes generados. HTML: %s, CSV: %s",
            report_result.html_s3_key or "N/A",
            report_result.csv_s3_key or "N/A",
        )

        # --- Etapa 8: Publicación web ---
        stage_start = time.time()
        publish_success = True

        if html_content and report_result.html_s3_key:
            filename = report_result.html_s3_key.split("/")[-1]
            publish_success = publish_report(
                html_content=html_content,
                filename=filename,
                bucket=REPORTS_SITE_BUCKET,
                s3_client=s3_client,
            )

            if publish_success:
                # Actualizar página índice
                existing_reports = _list_existing_reports(
                    s3_client, REPORTS_SITE_BUCKET
                )
                index_html = generate_index(existing_reports)
                try:
                    s3_client.put_object(
                        Bucket=REPORTS_SITE_BUCKET,
                        Key="index.html",
                        Body=index_html.encode("utf-8"),
                        ContentType="text/html",
                    )
                    logger.info("Página índice actualizada exitosamente.")
                except ClientError as e:
                    logger.warning(
                        "Error actualizando página índice: %s", str(e)
                    )

        stage_durations["publicacion"] = time.time() - stage_start

        if not publish_success:
            logger.warning(
                "La publicación web falló. El reporte existe en S3 con URL pre-firmada."
            )

        # --- Etapa 9: Notificación ---
        stage_start = time.time()

        report_urls = {}
        if report_result.html_url:
            report_urls["html"] = report_result.html_url
        if report_result.csv_url:
            report_urls["csv"] = report_result.csv_url

        total_duration = time.time() - start_time

        execution_result = ExecutionResult(
            execution_id=execution_id,
            period=period,
            reference_date=reference_date,
            status="SUCCEEDED",
            total_duration_seconds=total_duration,
            stage_durations=stage_durations,
            users_processed=processing_result.total_users_processed,
            data_size_bytes=total_data_size,
            report_urls=report_urls if report_urls else None,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Registrar resumen estructurado en CloudWatch
        summary = build_execution_summary(execution_result)
        logger.info("Resumen de ejecución: %s", json.dumps(summary, default=str))

        # Enviar notificación
        recipients = _get_notification_recipients()
        if recipients:
            notification_result = notify(
                execution_result=execution_result,
                report_urls=report_urls if report_urls else None,
                recipients=recipients,
            )
            if not notification_result.success:
                logger.warning(
                    "Fallo en notificación (no afecta estado del pipeline): %s",
                    notification_result.error,
                )

        stage_durations["notificacion"] = time.time() - stage_start

        # --- Emitir evento de completación a EventBridge ---
        report_paths = {}
        if report_result.html_s3_key:
            report_paths["html"] = report_result.html_s3_key
        if report_result.csv_s3_key:
            report_paths["csv"] = report_result.csv_s3_key

        events_client = boto3.client("events")
        _emit_completion_event(
            events_client=events_client,
            period=period,
            reference_date=reference_date,
            report_paths=report_paths,
        )

        # Actualizar estado de ejecución a completado
        _update_execution_status(
            dynamodb_client, period, reference_date, "SUCCEEDED"
        )

        return {
            "execution_id": execution_id,
            "status": "SUCCEEDED",
            "period": period,
            "reference_date": reference_date,
            "report_urls": report_urls if report_urls else None,
            "users_processed": processing_result.total_users_processed,
            "duration_seconds": total_duration,
            "publish_success": publish_success,
        }

    except Exception as e:
        # Manejar fallo del pipeline
        total_duration = time.time() - start_time
        error_msg = str(e)
        failure_stage = _determine_failure_stage(stage_durations)

        logger.error(
            "Pipeline fallido en etapa '%s': %s",
            failure_stage,
            error_msg,
        )

        # Construir resultado de fallo
        execution_result = ExecutionResult(
            execution_id=execution_id,
            period=period,
            reference_date=reference_date,
            status="FAILED",
            total_duration_seconds=total_duration,
            stage_durations=stage_durations,
            failure_stage=failure_stage,
            failure_message=error_msg,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Registrar resumen de fallo en CloudWatch
        summary = build_execution_summary(execution_result)
        logger.info(
            "Resumen de ejecución (FAILED): %s",
            json.dumps(summary, default=str),
        )

        # Intentar enviar notificación de fallo
        recipients = _get_notification_recipients()
        if recipients:
            try:
                notify(
                    execution_result=execution_result,
                    report_urls=None,
                    recipients=recipients,
                )
            except Exception as notify_err:
                logger.warning(
                    "Error al notificar fallo: %s", str(notify_err)
                )

        # Actualizar estado de ejecución a fallido
        _update_execution_status(
            dynamodb_client, period, reference_date, "FAILED"
        )

        return {
            "execution_id": execution_id,
            "status": "FAILED",
            "period": period,
            "reference_date": reference_date,
            "error": error_msg,
            "stage": failure_stage,
            "duration_seconds": total_duration,
        }


def _determine_failure_stage(stage_durations: Dict[str, float]) -> str:
    """
    Determina la etapa donde falló el pipeline según las duraciones registradas.

    La última etapa que no tiene duración registrada es donde falló.

    Args:
        stage_durations: Diccionario con duraciones de etapas completadas.

    Returns:
        Nombre de la etapa donde ocurrió el fallo.
    """
    # Orden de etapas del pipeline
    stages_order = [
        "lectura_roster",
        "recoleccion",
        "procesamiento",
        "analisis_ai",
        "generacion_reportes",
        "publicacion",
        "notificacion",
    ]

    for stage in stages_order:
        if stage not in stage_durations:
            return stage

    return "desconocida"


def check_duplicate_handler(event: dict, context=None) -> dict:
    """Handler Lambda para Step Functions — verifica ejecución duplicada."""
    params = event.get("validation", {}).get("Payload", {}).get("params", {})
    if not params:
        params = event.get("validation", {}).get("params", {})
    if not params:
        params = event

    period = params["period"]
    reference_date = params["reference_date"]

    dynamodb_client = boto3.client("dynamodb")
    duplicate_id = _check_duplicate_execution(dynamodb_client, period, reference_date)

    if duplicate_id:
        raise RuntimeError(
            f"Ejecución duplicada activa: {duplicate_id} "
            f"(period={period}, reference_date={reference_date})"
        )

    # Registrar esta ejecución
    execution_id = _generate_execution_id()
    _register_execution(dynamodb_client, execution_id, period, reference_date)

    return {"duplicate": False, "execution_id": execution_id}


def cleanup_handler(event: dict, context=None) -> dict:
    """Handler Lambda para Step Functions — limpia datos temporales."""
    from src.orchestrator.temp_cleanup import cleanup_temp_data

    reports_bucket = os.environ.get("REPORTS_BUCKET", "")

    # Usar execution_id determinístico basado en period+date
    params = event.get("validation", {}).get("Payload", {}).get("params", {})
    if not params:
        params = event.get("validation", {}).get("params", {})
    if not params:
        params = event
    period = params.get("period", "")
    reference_date = params.get("reference_date", "")
    execution_id = f"{period}_{reference_date}" if period else "manual"

    s3_client = boto3.client("s3")
    deleted = cleanup_temp_data(s3_client, reports_bucket, execution_id)

    return {"objects_deleted": deleted, "execution_id": execution_id}
