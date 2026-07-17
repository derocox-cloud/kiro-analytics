"""
Recolector genérico de datos desde S3.

Extrae datos crudos de S3 para una fuente específica (user_report, analytics, prompts),
filtra por usuarios habilitados del roster, y almacena el resultado en S3 temporal.
"""
from __future__ import annotations

import csv
import io
import logging
import sys
from datetime import date
from typing import List

from ..models import CollectionResult, CollectorConfig, User
from ..utils.date_utils import date_prefixes
from ..utils.s3_utils import (
    download_csv,
    download_json_gz,
    paginated_list_objects,
    upload_json,
)

logger = logging.getLogger(__name__)


def _get_enabled_user_ids(roster: List[User]) -> set:
    """Retorna el conjunto de user_ids con status 'Enabled' del roster."""
    return {user.user_id for user in roster if user.status == "Enabled"}


def _normalize_user_id(raw_id: str) -> str:
    """
    Normaliza un userId que puede tener prefijo (e.g. 'd-XXXX.userId').

    Extrae la parte después del último punto y elimina comillas.
    """
    uid = raw_id.split(".")[-1] if "." in raw_id else raw_id
    return uid.strip('"')


def _parse_csv_records(csv_content: str, enabled_ids: set) -> List[dict]:
    """
    Parsea contenido CSV y filtra registros por usuarios habilitados.

    Retorna lista de dicts con los registros que pertenecen a usuarios habilitados.
    """
    records = []
    reader = csv.DictReader(io.StringIO(csv_content))
    for row in reader:
        raw_uid = row.get("UserId", "")
        uid = _normalize_user_id(raw_uid)
        if uid in enabled_ids:
            row["_normalized_user_id"] = uid
            records.append(dict(row))
    return records


def _parse_json_gz_records(data: dict, enabled_ids: set) -> List[dict]:
    """
    Parsea contenido JSON.gz (prompts) y filtra registros por usuarios habilitados.

    Retorna lista de dicts con los registros que pertenecen a usuarios habilitados.
    """
    records = []
    for rec in data.get("records", []):
        req = rec.get("generateAssistantResponseEventRequest", {})
        raw_uid = req.get("userId", "")
        uid = _normalize_user_id(raw_uid)
        if uid in enabled_ids:
            rec["_normalized_user_id"] = uid
            records.append(rec)
    return records


def collect(
    config: CollectorConfig,
    roster: List[User],
    start_date: date,
    end_date: date,
    execution_id: str,
    s3_client=None,
    bucket: str = "",
    temp_bucket: str = "",
) -> CollectionResult:
    """
    Recolecta datos de S3 para el rango de fechas dado.

    Filtra por usuarios del roster con status Enabled.
    Almacena resultado en S3 temporal con prefijo tmp/{execution_id}/{source_type}/.
    Retorna resultado vacío (lista vacía) sin error si no hay archivos para la fuente.

    Args:
        config: Configuración del recolector (tipo de fuente, prefijo S3, extensión).
        roster: Lista de usuarios del roster.
        start_date: Fecha de inicio del rango.
        end_date: Fecha de fin del rango.
        execution_id: Identificador único de la ejecución del pipeline.
        s3_client: Cliente boto3 de S3 (inyectado para testing).
        bucket: Nombre del bucket S3 de origen de logs.
        temp_bucket: Nombre del bucket S3 temporal para almacenar resultados.

    Returns:
        CollectionResult con los registros recolectados y metadata.
    """
    result = CollectionResult(source_type=config.source_type)

    if s3_client is None:
        logger.error("Se requiere un cliente S3 para la recolección.")
        result.errors.append("Cliente S3 no proporcionado.")
        return result

    # Obtener IDs de usuarios habilitados
    enabled_ids = _get_enabled_user_ids(roster)
    if not enabled_ids:
        logger.warning("No hay usuarios habilitados en el roster.")
        return result

    # Generar prefijos de fecha para el rango
    prefixes = date_prefixes(start_date, end_date)

    all_records: List[dict] = []
    total_size_bytes = 0
    file_count = 0

    for date_prefix in prefixes:
        # Construir prefijo S3 completo para esta fecha
        full_prefix = f"{config.s3_prefix}/{date_prefix}"
        daily_file_count = 0

        # Listar objetos con paginación (maneja >1000 archivos)
        objects = paginated_list_objects(s3_client, bucket, full_prefix)

        for obj in objects:
            key = obj["Key"]
            size = obj.get("Size", 0)

            # Filtrar por extensión de archivo
            if not key.endswith(config.file_extension):
                continue

            # Respetar límite de archivos por día (0 = sin límite)
            if config.max_files_per_day > 0 and daily_file_count >= config.max_files_per_day:
                logger.info(
                    "Límite de archivos por día alcanzado (%d) para %s en %s",
                    config.max_files_per_day,
                    config.source_type,
                    date_prefix,
                )
                break

            daily_file_count += 1

            try:
                if config.file_extension == ".csv":
                    csv_content = download_csv(s3_client, bucket, key)
                    records = _parse_csv_records(csv_content, enabled_ids)
                elif config.file_extension == ".json.gz":
                    json_data = download_json_gz(s3_client, bucket, key)
                    records = _parse_json_gz_records(json_data, enabled_ids)
                else:
                    logger.warning(
                        "Extensión no soportada: %s", config.file_extension
                    )
                    continue

                all_records.extend(records)
                total_size_bytes += size
                file_count += 1

            except Exception as e:
                error_msg = f"Error procesando {key}: {str(e)}"
                logger.warning(error_msg)
                result.errors.append(error_msg)
                continue

    # Almacenar resultado en S3 temporal
    if all_records and temp_bucket:
        temp_key = f"tmp/{execution_id}/{config.source_type}/data.json"
        try:
            upload_json(s3_client, temp_bucket, temp_key, all_records)
            logger.info(
                "Datos almacenados en s3://%s/%s (%d registros)",
                temp_bucket,
                temp_key,
                len(all_records),
            )
        except Exception as e:
            error_msg = f"Error almacenando resultado temporal: {str(e)}"
            logger.warning(error_msg)
            result.errors.append(error_msg)

    # Construir resultado
    result.records = all_records
    result.file_count = file_count
    result.data_size_bytes = total_size_bytes

    logger.info(
        "Recolección completada para '%s': %d archivos, %d registros, %d bytes",
        config.source_type,
        file_count,
        len(all_records),
        total_size_bytes,
    )

    return result


def lambda_handler(event: dict, context=None) -> dict:
    """Handler Lambda para Step Functions — recolecta datos de una fuente S3."""
    import os
    from datetime import date as date_type

    import boto3

    from ..collectors.sources import get_config_for_source, read_roster_from_s3

    source_type = os.environ["SOURCE_TYPE"]
    logs_bucket = os.environ["LOGS_BUCKET"]
    reports_bucket = os.environ["REPORTS_BUCKET"]
    roster_s3_path = os.environ["ROSTER_S3_PATH"]

    # Parsear roster path: s3://bucket/key
    roster_parts = roster_s3_path.replace("s3://", "").split("/", 1)
    roster_bucket = roster_parts[0]
    roster_key = roster_parts[1]

    # Extraer params del evento (viene de validación previa en Step Functions)
    params = event.get("validation", {}).get("Payload", {}).get("params", {})
    if not params:
        params = event.get("validation", {}).get("params", {})
    if not params:
        params = event

    period = params["period"]
    reference_date = params["reference_date"]

    from ..utils.date_utils import get_date_range

    ref_date = date_type.fromisoformat(reference_date)
    start_date, end_date = get_date_range(period, ref_date)

    # Para user_report, extender el rango al día 1 del mes para calcular credits_monthly
    if source_type == "user_report" and start_date.day != 1:
        start_date = start_date.replace(day=1)

    s3_client = boto3.client("s3")
    config = get_config_for_source(source_type)

    # Para periodos mensuales, reducir max_files_per_day de prompts para mantener
    # el tiempo de ejecución razonable (muestra representativa de las 4 semanas)
    if period == "monthly" and config.max_files_per_day > 0:
        config = CollectorConfig(
            source_type=config.source_type,
            s3_prefix=config.s3_prefix,
            file_extension=config.file_extension,
            max_files_per_day=125,  # 125/día × 30 días = ~3750 archivos (vs 15000)
        )

    roster = read_roster_from_s3(s3_client, roster_bucket, roster_key)

    # Usar execution_id determinístico basado en period+date para consistencia
    # entre handlers que pueden no tener acceso al state completo (ej: Parallel)
    execution_id = f"{period}_{reference_date}"

    result = collect(
        config=config,
        roster=roster,
        start_date=start_date,
        end_date=end_date,
        execution_id=execution_id,
        s3_client=s3_client,
        bucket=logs_bucket,
        temp_bucket=reports_bucket,
    )

    return {
        "source_type": result.source_type,
        "file_count": result.file_count,
        "record_count": len(result.records),
        "data_size_bytes": result.data_size_bytes,
        "errors": result.errors,
    }
