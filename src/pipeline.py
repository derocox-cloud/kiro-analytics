"""
Punto de entrada principal del pipeline de analytics de Kiro.

Conecta todos los componentes en el flujo completo:
validación → recolección → procesamiento → análisis AI → reportes → publicación → notificación.

Implementa:
- Manejo del flag `ai_analysis` para omitir la etapa de análisis AI (Req 4.4)
- Degradación elegante:
  * Si Bedrock falla → reporte sin sección AI (Req 4.5)
  * Si la publicación falla → continúa con indicador de fallo parcial (Req 8.6)
- Flujo orquestado con registro de duraciones por etapa (Req 1.1)

Este módulo sirve como abstracción del flujo del pipeline, utilizable tanto
por el handler Lambda (orchestrator/handler.py) como por ejecuciones locales.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from src.analyzers.ai_analyzer import analyze_prompts
from src.collectors.collector import collect
from src.collectors.sources import get_source_configs, read_roster_from_s3, LOGS_BUCKET
from src.generators.csv_generator import generate_csv
from src.generators.html_generator import generate_html
from src.generators.index_generator import generate_index
from src.generators.report_storage import store_reports
from src.generators.site_publisher import publish_report
from src.models import (
    AIAnalysisResult,
    CollectionResult,
    ExecutionResult,
    NotificationResult,
    PipelineInput,
    ReportGenerationResult,
    ReportMetadata,
    User,
)
from src.notifiers.notifier import notify
from src.processors.categorizer import categorize_prompts
from src.processors.metrics_processor import process_metrics
from src.utils.date_utils import get_date_range
from src.utils.execution_summary import build_execution_summary
from src.validators.input_validator import validate_input

logger = logging.getLogger(__name__)


class PipelineResult:
    """Resultado de la ejecución del pipeline con indicadores de degradación."""

    def __init__(self):
        """Inicializa el resultado del pipeline con valores por defecto."""
        self.execution_id: str = ""
        self.status: str = "SUCCEEDED"
        self.period: str = ""
        self.reference_date: str = ""
        self.report_urls: Optional[Dict[str, str]] = None
        self.users_processed: int = 0
        self.duration_seconds: float = 0.0
        self.stage_durations: Dict[str, float] = {}
        self.publish_success: bool = True
        self.ai_available: bool = True
        self.ai_skipped: bool = False
        self.error: Optional[str] = None
        self.failure_stage: Optional[str] = None
        self.data_size_bytes: int = 0


def run_pipeline(
    event: dict,
    s3_client=None,
    dynamodb_client=None,
    sns_client=None,
    roster_bucket: str = "",
    roster_key: str = "config/kiro-users-dev.csv",
    temp_bucket: str = "",
    site_bucket: str = "",
    recipients: Optional[List[str]] = None,
) -> PipelineResult:
    """
    Ejecuta el flujo completo del pipeline de analytics.

    Orquesta todas las etapas en orden:
    1. Validación de parámetros de entrada
    2. Lectura del roster de usuarios desde S3
    3. Recolección paralela de datos (user_report, by_user_analytic, prompt-metadata)
    4. Procesamiento y agregación de métricas por usuario
    5. Análisis AI con Bedrock (condicional según flag ai_analysis)
    6. Generación de reportes (HTML y/o CSV)
    7. Publicación en sitio web y actualización de índice
    8. Notificación de resultado

    Degradación elegante:
    - Si Bedrock falla después de reintentos → genera reporte sin sección AI
    - Si la publicación web falla después de reintentos → continúa con indicador

    Args:
        event: Diccionario con parámetros del pipeline:
            - period: "daily" | "weekly" | "monthly"
            - reference_date: "YYYY-MM-DD"
            - ai_analysis: bool (default True)
            - output_format: "html" | "csv" | "both" (default "both")
        s3_client: Cliente boto3 de S3 (inyectable para testing).
        dynamodb_client: Cliente boto3 de DynamoDB (inyectable para testing).
        sns_client: Cliente boto3 de SNS (inyectable para testing).
        roster_bucket: Bucket donde se encuentra el roster de usuarios.
        roster_key: Clave S3 del archivo de roster.
        temp_bucket: Bucket temporal para datos intermedios.
        site_bucket: Bucket del sitio web de reportes.
        recipients: Lista de destinatarios de notificación.

    Returns:
        PipelineResult con el resultado de la ejecución y metadatos.
    """
    result = PipelineResult()
    result.execution_id = str(uuid.uuid4())
    start_time = time.time()

    logger.info(
        "Iniciando pipeline. ID: %s, Evento: %s",
        result.execution_id,
        event,
    )

    # =========================================================================
    # Etapa 1: Validación de entrada
    # =========================================================================
    stage_start = time.time()
    validation = validate_input(event)
    result.stage_durations["validacion"] = time.time() - stage_start

    if not validation.valid:
        logger.error("Validación fallida: %s", validation.error)
        result.status = "FAILED"
        result.error = validation.error
        result.failure_stage = "validacion"
        result.duration_seconds = time.time() - start_time
        return result

    params: PipelineInput = validation.params
    result.period = params.period
    result.reference_date = params.reference_date

    # Calcular rango de fechas para el periodo
    ref_date = date.fromisoformat(params.reference_date)
    start_date, end_date = get_date_range(params.period, ref_date)

    # =========================================================================
    # Etapa 2: Lectura del roster de usuarios
    # =========================================================================
    stage_start = time.time()
    try:
        # Determinar bucket del roster
        bucket_roster = roster_bucket or LOGS_BUCKET
        roster = read_roster_from_s3(s3_client, bucket_roster, roster_key)
        logger.info("Roster cargado: %d usuarios", len(roster))
    except Exception as e:
        logger.error("Error leyendo roster: %s", str(e))
        result.status = "FAILED"
        result.error = f"Error leyendo roster: {str(e)}"
        result.failure_stage = "lectura_roster"
        result.duration_seconds = time.time() - start_time
        result.stage_durations["lectura_roster"] = time.time() - stage_start
        return result
    result.stage_durations["lectura_roster"] = time.time() - stage_start

    # =========================================================================
    # Etapa 3: Recolección paralela de datos
    # =========================================================================
    stage_start = time.time()
    try:
        raw_data = _collect_all_sources(
            roster=roster,
            start_date=start_date,
            end_date=end_date,
            execution_id=result.execution_id,
            s3_client=s3_client,
            temp_bucket=temp_bucket,
        )
        result.data_size_bytes = sum(
            r.data_size_bytes for r in raw_data.values()
        )
        logger.info(
            "Recolección completada: %d fuentes, %d bytes",
            len(raw_data),
            result.data_size_bytes,
        )
    except Exception as e:
        logger.error("Error en recolección: %s", str(e))
        result.status = "FAILED"
        result.error = f"Error en recolección: {str(e)}"
        result.failure_stage = "recoleccion"
        result.duration_seconds = time.time() - start_time
        result.stage_durations["recoleccion"] = time.time() - stage_start
        return result
    result.stage_durations["recoleccion"] = time.time() - stage_start

    # =========================================================================
    # Etapa 4: Procesamiento y agregación de métricas
    # =========================================================================
    stage_start = time.time()
    try:
        processing_result = process_metrics(
            raw_data=raw_data,
            roster=roster,
            period=params.period,
            start_date=start_date,
            end_date=end_date,
        )
        result.users_processed = processing_result.total_users_processed
        logger.info(
            "Procesamiento completado: %d usuarios activos, %d inactivos",
            processing_result.total_users_processed,
            len(processing_result.inactive_users),
        )
    except Exception as e:
        logger.error("Error en procesamiento: %s", str(e))
        result.status = "FAILED"
        result.error = f"Error en procesamiento: {str(e)}"
        result.failure_stage = "procesamiento"
        result.duration_seconds = time.time() - start_time
        result.stage_durations["procesamiento"] = time.time() - stage_start
        return result
    result.stage_durations["procesamiento"] = time.time() - stage_start

    # =========================================================================
    # Etapa 5: Análisis AI con Bedrock (condicional)
    # =========================================================================
    ai_result: Optional[AIAnalysisResult] = None

    if params.ai_analysis:
        stage_start = time.time()
        ai_result = _run_ai_analysis(raw_data, roster)
        result.stage_durations["analisis_ai"] = time.time() - stage_start

        if ai_result.available:
            result.ai_available = True
            logger.info(
                "Análisis AI completado: %d tokens", ai_result.tokens_used
            )
        else:
            # Degradación elegante: Bedrock falló, continúa sin AI (Req 4.5)
            result.ai_available = False
            logger.warning(
                "Análisis AI no disponible (degradación elegante): %s",
                ai_result.error_message,
            )
    else:
        # Flag ai_analysis deshabilitado: omitir etapa (Req 4.4)
        result.ai_skipped = True
        result.ai_available = False
        logger.info("Análisis AI omitido (flag ai_analysis=False).")

    # =========================================================================
    # Etapa 6: Generación de reportes
    # =========================================================================
    stage_start = time.time()
    try:
        start_date_str = start_date.isoformat()
        end_date_str = end_date.isoformat()

        html_content = None
        csv_content = None

        if params.output_format in ("html", "both"):
            html_content = generate_html(
                metrics=processing_result,
                ai_analysis=ai_result,
                period=params.period,
                start_date=start_date_str,
                end_date=end_date_str,
            )

        if params.output_format in ("csv", "both"):
            csv_content = generate_csv(
                metrics=processing_result,
                period=params.period,
                start_date=start_date_str,
                end_date=end_date_str,
            )

        # Almacenar en S3 y generar URLs pre-firmadas
        report_result = store_reports(
            html=html_content,
            csv_content=csv_content,
            period=params.period,
            start_date=start_date_str,
            end_date=end_date_str,
            output_format=params.output_format,
            s3_client=s3_client,
        )

        # Construir diccionario de URLs
        report_urls: Dict[str, str] = {}
        if report_result.html_url:
            report_urls["html"] = report_result.html_url
        if report_result.csv_url:
            report_urls["csv"] = report_result.csv_url
        result.report_urls = report_urls if report_urls else None

        logger.info(
            "Reportes generados. HTML: %s, CSV: %s",
            report_result.html_s3_key or "N/A",
            report_result.csv_s3_key or "N/A",
        )
    except Exception as e:
        logger.error("Error generando reportes: %s", str(e))
        result.status = "FAILED"
        result.error = f"Error generando reportes: {str(e)}"
        result.failure_stage = "generacion_reportes"
        result.duration_seconds = time.time() - start_time
        result.stage_durations["generacion_reportes"] = time.time() - stage_start
        return result
    result.stage_durations["generacion_reportes"] = time.time() - stage_start

    # =========================================================================
    # Etapa 7: Publicación en sitio web (degradación elegante, Req 8.6)
    # =========================================================================
    stage_start = time.time()
    publish_success = True

    if html_content and report_result.html_s3_key and site_bucket:
        filename = report_result.html_s3_key.split("/")[-1]
        publish_success = publish_report(
            html_content=html_content,
            filename=filename,
            bucket=site_bucket,
            s3_client=s3_client,
        )

        if publish_success:
            # Actualizar página índice
            _update_site_index(s3_client, site_bucket)
        else:
            # Degradación elegante: publicación falló, continúa con indicador (Req 8.6)
            logger.warning(
                "Publicación web falló (degradación elegante). "
                "El reporte existe en S3 con URL pre-firmada."
            )

    result.publish_success = publish_success
    result.stage_durations["publicacion"] = time.time() - stage_start

    # =========================================================================
    # Etapa 8: Notificación
    # =========================================================================
    stage_start = time.time()

    total_duration = time.time() - start_time
    result.duration_seconds = total_duration

    # Construir resultado de ejecución para notificación y resumen
    execution_result = ExecutionResult(
        execution_id=result.execution_id,
        period=params.period,
        reference_date=params.reference_date,
        status="SUCCEEDED",
        total_duration_seconds=total_duration,
        stage_durations=result.stage_durations,
        users_processed=result.users_processed,
        data_size_bytes=result.data_size_bytes,
        report_urls=result.report_urls,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # Registrar resumen de ejecución en logs
    summary = build_execution_summary(execution_result)
    logger.info("Resumen de ejecución: %s", summary)

    # Enviar notificación (best-effort, no afecta estado del pipeline)
    if recipients:
        notification_result = notify(
            execution_result=execution_result,
            report_urls=result.report_urls,
            recipients=recipients,
            sns_client=sns_client,
        )
        if not notification_result.success:
            logger.warning(
                "Notificación falló (no afecta pipeline): %s",
                notification_result.error,
            )

    result.stage_durations["notificacion"] = time.time() - stage_start

    logger.info(
        "Pipeline completado exitosamente en %.2fs. "
        "Usuarios procesados: %d, AI disponible: %s, Publicación exitosa: %s",
        result.duration_seconds,
        result.users_processed,
        result.ai_available,
        result.publish_success,
    )

    return result


def _collect_all_sources(
    roster: List[User],
    start_date: date,
    end_date: date,
    execution_id: str,
    s3_client,
    temp_bucket: str,
) -> Dict[str, CollectionResult]:
    """
    Recolecta datos de todas las fuentes configuradas.

    Ejecuta la recolección de datos para cada fuente (user_report,
    by_user_analytic, prompt-metadata) secuencialmente. Si alguna
    fuente falla, lanza una excepción que detiene el pipeline.

    Args:
        roster: Lista de usuarios del roster.
        start_date: Fecha de inicio del rango.
        end_date: Fecha de fin del rango.
        execution_id: Identificador de la ejecución.
        s3_client: Cliente boto3 de S3.
        temp_bucket: Bucket temporal para datos intermedios.

    Returns:
        Diccionario {source_type: CollectionResult}.

    Raises:
        RuntimeError: Si la recolección de alguna fuente falla.
    """
    source_configs = get_source_configs()
    results: Dict[str, CollectionResult] = {}

    for source_name, config in source_configs.items():
        try:
            result = collect(
                config=config,
                roster=roster,
                start_date=start_date,
                end_date=end_date,
                execution_id=execution_id,
                s3_client=s3_client,
                bucket=LOGS_BUCKET,
                temp_bucket=temp_bucket,
            )
            results[source_name] = result
        except Exception as e:
            raise RuntimeError(
                f"Fallo en recolección de '{source_name}': {str(e)}"
            ) from e

    return results


def _run_ai_analysis(
    raw_data: Dict[str, CollectionResult],
    roster: List[User],
) -> AIAnalysisResult:
    """
    Ejecuta el análisis AI con Bedrock sobre los prompts recolectados.

    Prepara los prompts por usuario y los envía al analizador AI.
    Si Bedrock falla después de los reintentos, retorna un resultado
    degradado (available=False) para que el pipeline continúe sin la
    sección de análisis AI en el reporte (Req 4.5).

    Args:
        raw_data: Datos crudos recolectados por fuente.
        roster: Lista de usuarios del roster.

    Returns:
        AIAnalysisResult con análisis disponible o resultado degradado.
    """
    # Construir diccionario de prompts por usuario
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

    # Construir diccionario de usuarios habilitados
    users_dict = {u.user_id: u for u in roster if u.status == "Enabled"}

    # Invocar análisis AI (maneja reintentos internamente)
    # Si falla, retorna resultado degradado con available=False
    return analyze_prompts(prompts_by_user, users_dict)


def _update_site_index(s3_client, site_bucket: str) -> None:
    """
    Actualiza la página índice del sitio de reportes.

    Lista los reportes existentes en el bucket y regenera el index.html.
    Si falla, registra el error en logs sin afectar el pipeline.

    Args:
        s3_client: Cliente boto3 de S3.
        site_bucket: Nombre del bucket del sitio de reportes.
    """
    try:
        existing_reports = _list_site_reports(s3_client, site_bucket)
        index_html = generate_index(existing_reports)
        s3_client.put_object(
            Bucket=site_bucket,
            Key="index.html",
            Body=index_html.encode("utf-8"),
            ContentType="text/html",
        )
        logger.info("Página índice actualizada exitosamente.")
    except Exception as e:
        logger.warning("Error actualizando página índice: %s", str(e))


def _list_site_reports(s3_client, bucket: str) -> List[ReportMetadata]:
    """
    Lista los reportes HTML existentes en el bucket del sitio.

    Parsea el nombre del archivo para extraer metadata del reporte
    (periodo, fechas de cobertura, fecha de generación).

    Args:
        s3_client: Cliente boto3 de S3.
        bucket: Nombre del bucket del sitio de reportes.

    Returns:
        Lista de ReportMetadata con los reportes disponibles.
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

                # Parsear metadata del nombre: kiro_report_{period}_{start}_{end}.html
                filename = key.split("/")[-1]
                parts = filename.replace(".html", "").split("_")
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

    except Exception as e:
        logger.warning("Error listando reportes del sitio: %s", str(e))

    return reports
