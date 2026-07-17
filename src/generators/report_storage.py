"""
Almacenamiento de reportes en S3 y generación de URLs pre-firmadas.

Sube reportes HTML y/o CSV al bucket de reportes configurado,
genera URLs pre-firmadas con validez de 7 días para acceso directo,
y retorna el resultado con las claves S3 y URLs generadas.

También incluye funciones de consulta a DynamoDB para métricas históricas.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from src.models import ReportGenerationResult

logger = logging.getLogger(__name__)

# Validez de las URLs pre-firmadas: 7 días en segundos
PRESIGNED_URL_EXPIRATION = 604800

# Nombre del bucket de reportes (configurable por variable de entorno)
DEFAULT_REPORTS_BUCKET = "kiro-analytics-reports"

# Nombre de la tabla DynamoDB de métricas (misma convención que dynamodb_writer)
DEFAULT_TABLE_NAME = "kiro-analytics-metrics"

# Configuración de reintentos para queries a DynamoDB
_MAX_RETRIES = 3
_BACKOFF_SECONDS = [1, 2, 4]


def _get_reports_bucket() -> str:
    """
    Obtiene el nombre del bucket de reportes desde la variable de entorno
    REPORTS_BUCKET, o usa el valor por defecto.
    """
    return os.environ.get("REPORTS_BUCKET", DEFAULT_REPORTS_BUCKET)


def _get_metrics_table_name(table_name: str | None = None) -> str:
    """
    Resuelve el nombre de la tabla DynamoDB de métricas con prioridad:
    1. Parámetro explícito table_name
    2. Variable de entorno DYNAMODB_TABLE_NAME
    3. Valor por defecto "kiro-analytics-metrics"
    """
    if table_name:
        return table_name
    return os.environ.get("DYNAMODB_TABLE_NAME") or DEFAULT_TABLE_NAME


def query_user_metrics(
    user_id: str,
    period: str,
    table_name: str | None = None,
    dynamodb_resource: Any = None,
    max_items: int = 100,
) -> List[Dict[str, Any]]:
    """
    Consulta métricas históricas de un usuario por periodo desde DynamoDB.

    Ejecuta una Query con PK=user_id y SK begins_with({period}_).
    Pagina resultados con LastEvaluatedKey hasta alcanzar max_items.
    Reintenta hasta 3 veces con backoff exponencial (1s, 2s, 4s) en caso de error.
    Si falla tras todos los reintentos, retorna lista vacía.

    Args:
        user_id: Identificador del usuario (Partition Key).
        period: Periodo a consultar ("daily", "weekly", "monthly").
        table_name: Nombre de la tabla (opcional, usa env var o default).
        dynamodb_resource: Recurso DynamoDB de boto3 (opcional, para testing con moto).
        max_items: Número máximo de items a retornar (default 100).

    Returns:
        Lista de items (dicts) con las métricas del usuario para el periodo,
        o lista vacía si no hay resultados o si ocurre un error irrecuperable.
    """
    resolved_table_name = _get_metrics_table_name(table_name)

    if dynamodb_resource is None:
        dynamodb_resource = boto3.resource("dynamodb")

    table = dynamodb_resource.Table(resolved_table_name)

    items: List[Dict[str, Any]] = []

    for attempt in range(_MAX_RETRIES):
        try:
            query_kwargs: Dict[str, Any] = {
                "KeyConditionExpression": (
                    boto3.dynamodb.conditions.Key("user_id").eq(user_id)
                    & boto3.dynamodb.conditions.Key("periodo").begins_with(f"{period}_")
                ),
            }

            exclusive_start_key = None

            while len(items) < max_items:
                if exclusive_start_key:
                    query_kwargs["ExclusiveStartKey"] = exclusive_start_key

                response = table.query(**query_kwargs)
                returned_items = response.get("Items", [])
                items.extend(returned_items)

                exclusive_start_key = response.get("LastEvaluatedKey")
                if not exclusive_start_key:
                    break

            # Limitar al máximo solicitado
            items = items[:max_items]
            return items

        except ClientError as e:
            if attempt < _MAX_RETRIES - 1:
                sleep_time = _BACKOFF_SECONDS[attempt]
                logger.warning(
                    "Error en Query a DynamoDB (intento %d/%d), reintentando en %ds: %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    sleep_time,
                    e.response["Error"]["Message"],
                )
                time.sleep(sleep_time)
                items = []  # Reiniciar items para el próximo intento
            else:
                logger.error(
                    "Error en Query a DynamoDB tras %d reintentos para user_id='%s', "
                    "period='%s', tabla='%s': %s",
                    _MAX_RETRIES,
                    user_id,
                    period,
                    resolved_table_name,
                    e.response["Error"]["Message"],
                )
                return []

    return []


def _build_s3_key(period: str, start_date: str, end_date: str, ext: str) -> str:
    """
    Construye la clave S3 para un reporte con la nomenclatura estándar.

    Formato: kiro_report_{period}_{start_date}_{end_date}.{ext}
    Las fechas deben estar en formato YYYY-MM-DD.

    Args:
        period: Periodo del reporte ("daily", "weekly", "monthly").
        start_date: Fecha de inicio en formato YYYY-MM-DD.
        end_date: Fecha de fin en formato YYYY-MM-DD.
        ext: Extensión del archivo ("html" o "csv").

    Returns:
        Clave S3 con la nomenclatura estándar.
    """
    return f"reports/kiro_report_{period}_{start_date}_{end_date}.{ext}"


def _upload_to_s3(
    s3_client,
    bucket: str,
    key: str,
    content: str,
    content_type: str,
) -> None:
    """
    Sube contenido de texto a S3 con el content-type especificado.

    Args:
        s3_client: Cliente boto3 de S3.
        bucket: Nombre del bucket destino.
        key: Clave S3 del objeto.
        content: Contenido del archivo como string.
        content_type: Tipo MIME del contenido.

    Raises:
        ClientError: Si la operación de subida falla.
    """
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType=content_type,
    )


def _generate_presigned_url(s3_client, bucket: str, key: str) -> str:
    """
    Genera una URL pre-firmada para acceder a un objeto en S3.

    La URL tiene validez de 7 días (604800 segundos).

    Args:
        s3_client: Cliente boto3 de S3.
        bucket: Nombre del bucket.
        key: Clave S3 del objeto.

    Returns:
        URL pre-firmada como string.
    """
    url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=PRESIGNED_URL_EXPIRATION,
    )
    return url


def store_reports(
    html: Optional[str],
    csv_content: Optional[str],
    period: str,
    start_date: str,
    end_date: str,
    output_format: str = "both",
    s3_client=None,
) -> ReportGenerationResult:
    """
    Almacena reportes en S3 y genera URLs pre-firmadas con validez de 7 días.

    Sube los reportes HTML y/o CSV al bucket de reportes configurado,
    según el parámetro output_format. Genera URLs pre-firmadas para
    cada archivo almacenado exitosamente.

    Args:
        html: Contenido del reporte HTML (puede ser None si no se genera).
        csv_content: Contenido del reporte CSV (puede ser None si no se genera).
        period: Periodo del reporte ("daily", "weekly", "monthly").
        start_date: Fecha de inicio en formato YYYY-MM-DD.
        end_date: Fecha de fin en formato YYYY-MM-DD.
        output_format: Formato de salida ("html", "csv", "both"). Por defecto "both".
        s3_client: Cliente boto3 de S3 (opcional, se crea uno si no se provee).

    Returns:
        ReportGenerationResult con las URLs pre-firmadas y claves S3 de los
        reportes almacenados, o con campos vacíos si ocurre un error.
    """
    start_time = time.time()
    result = ReportGenerationResult()

    # Crear cliente S3 si no se proporcionó uno
    if s3_client is None:
        s3_client = boto3.client("s3")

    bucket = _get_reports_bucket()

    try:
        # Almacenar reporte HTML si corresponde
        if output_format in ("html", "both") and html is not None:
            html_key = _build_s3_key(period, start_date, end_date, "html")
            _upload_to_s3(s3_client, bucket, html_key, html, "text/html")
            html_url = _generate_presigned_url(s3_client, bucket, html_key)
            result.html_s3_key = html_key
            result.html_url = html_url

        # Almacenar reporte CSV si corresponde
        if output_format in ("csv", "both") and csv_content is not None:
            csv_key = _build_s3_key(period, start_date, end_date, "csv")
            _upload_to_s3(s3_client, bucket, csv_key, csv_content, "text/csv")
            csv_url = _generate_presigned_url(s3_client, bucket, csv_key)
            result.csv_s3_key = csv_key
            result.csv_url = csv_url

    except ClientError as e:
        # Si el almacenamiento falla, retornar error con causa para reintento
        error_msg = str(e)
        # Registrar la duración incluso en caso de error
        result.generation_duration_seconds = time.time() - start_time
        # Relanzar la excepción para que el orquestador pueda reintentar
        raise RuntimeError(
            f"Error al almacenar reporte en S3 (bucket={bucket}): {error_msg}"
        ) from e

    result.generation_duration_seconds = time.time() - start_time
    return result


def lambda_handler(event: dict, context=None) -> dict:
    """Handler Lambda para Step Functions — genera y almacena reportes."""
    import os
    from datetime import date as date_type

    from src.collectors.sources import read_roster_from_s3
    from src.generators.html_generator import generate_html
    from src.generators.csv_generator import generate_csv
    from src.models import AIAnalysisResult, CollectionResult
    from src.processors.metrics_processor import process_metrics
    from src.utils.date_utils import get_date_range
    from src.utils.s3_utils import download_json

    reports_bucket = os.environ["REPORTS_BUCKET"]

    params = event.get("validation", {}).get("Payload", {}).get("params", {})
    if not params:
        params = event.get("validation", {}).get("params", {})
    if not params:
        params = event

    period = params["period"]
    reference_date = params["reference_date"]
    output_format = params.get("output_format", "both")

    ref_date = date_type.fromisoformat(reference_date)
    start_date, end_date = get_date_range(period, ref_date)

    s3_client = boto3.client("s3")

    # Usar execution_id determinístico basado en period+date
    execution_id = f"{period}_{reference_date}"

    # Leer datos recolectados del S3 temporal
    raw_data = {}
    for source_type in ["user_report", "by_user_analytic", "prompt-metadata"]:
        temp_key = f"tmp/{execution_id}/{source_type}/data.json"
        try:
            records = download_json(s3_client, reports_bucket, temp_key)
            raw_data[source_type] = CollectionResult(
                source_type=source_type, records=records, file_count=1,
                data_size_bytes=0,
            )
        except Exception:
            raw_data[source_type] = CollectionResult(source_type=source_type)

    # Leer roster
    roster_s3_path = os.environ.get("ROSTER_S3_PATH", "")
    roster = []
    if roster_s3_path:
        parts = roster_s3_path.replace("s3://", "").split("/", 1)
        roster = read_roster_from_s3(s3_client, parts[0], parts[1])

    # Procesar métricas
    processing_result = process_metrics(
        raw_data=raw_data, roster=roster, period=period,
        start_date=start_date, end_date=end_date,
    )

    # Consultar métricas históricas por usuario desde DynamoDB
    historical_metrics: Dict[str, List[Dict[str, Any]]] = {}
    try:
        for user_metric in processing_result.user_metrics:
            user_historical = query_user_metrics(
                user_id=user_metric.user_id,
                period=period,
            )
            if user_historical:
                historical_metrics[user_metric.user_id] = user_historical
    except Exception as e:
        logger.error(
            "Error inesperado al consultar métricas históricas de DynamoDB: %s",
            str(e),
        )
        historical_metrics = {}

    logger.info(
        "Métricas históricas encontradas para %d/%d usuarios",
        len(historical_metrics),
        len(processing_result.user_metrics),
    )

    # Obtener análisis AI si disponible
    ai_result = None
    ai_data = event.get("ai_analysis", {})
    if isinstance(ai_data, dict):
        payload = ai_data.get("Payload", ai_data)
        if payload.get("available"):
            ai_result = AIAnalysisResult(
                analysis_text=payload.get("analysis_text", ""),
                available=True,
                model_used=payload.get("model_used", ""),
                tokens_used=payload.get("tokens_used", 0),
                duration_seconds=payload.get("duration_seconds", 0.0),
            )

    # Generar reportes
    html = None
    csv_content = None

    # Leer prompts para la sección de muestras
    prompts_by_user = {}
    try:
        temp_key = f"tmp/{execution_id}/prompt-metadata/data.json"
        prompt_records = download_json(s3_client, reports_bucket, temp_key)
        for rec in prompt_records:
            uid = rec.get("_normalized_user_id", "")
            req = rec.get("generateAssistantResponseEventRequest", {})
            prompt_text = req.get("prompt", "")
            if uid and prompt_text and len(prompt_text.strip()) > 5:
                prompts_by_user.setdefault(uid, []).append(prompt_text[:200])
    except Exception:
        pass

    if output_format in ("html", "both"):
        html = generate_html(
            metrics=processing_result,
            ai_analysis=ai_result,
            period=period,
            start_date=str(start_date),
            end_date=str(end_date),
            prompts_by_user=prompts_by_user,
        )
    if output_format in ("csv", "both"):
        csv_content = generate_csv(
            metrics=processing_result,
            period=period,
            start_date=str(start_date),
            end_date=str(end_date),
        )

    # Almacenar
    result = store_reports(
        html=html,
        csv_content=csv_content,
        period=period,
        start_date=str(start_date),
        end_date=str(end_date),
        output_format=output_format,
        s3_client=s3_client,
    )

    return {
        "html_url": result.html_url,
        "csv_url": result.csv_url,
        "html_s3_key": result.html_s3_key,
        "csv_s3_key": result.csv_s3_key,
        "duration_seconds": result.generation_duration_seconds,
    }
