"""
Publicación de reportes HTML en el sitio web de reportes (S3 + CloudFront).

Publica reportes HTML en el bucket del Sitio_Reportes, manteniendo la
nomenclatura original del archivo. Implementa reintentos (hasta 2 veces)
y continúa con notificación si persiste el fallo.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError

# Configuración de logging
logger = logging.getLogger(__name__)

# Número máximo de reintentos en caso de fallo de publicación
MAX_RETRIES = 2

# Tiempo de espera entre reintentos (segundos)
RETRY_DELAY_SECONDS = 5

# Tiempo máximo permitido para la publicación (60 segundos según requisito 8.1)
MAX_PUBLISH_TIME_SECONDS = 60


def publish_report(
    html_content: str,
    filename: str,
    bucket: str,
    s3_client=None,
) -> bool:
    """
    Publica un reporte HTML en el Sitio_Reportes (bucket S3 con CloudFront).

    Sube el archivo HTML al bucket especificado manteniendo la nomenclatura
    original. Reintenta hasta 2 veces si falla la publicación. Si persiste
    el fallo después de los reintentos, retorna False para que el pipeline
    continúe con una notificación indicando que la publicación no fue exitosa.

    La publicación debe completarse dentro de 60 segundos posteriores a la
    generación del reporte.

    Args:
        html_content: Contenido HTML del reporte a publicar.
        filename: Nombre del archivo con nomenclatura estándar
                  (ej: kiro_report_daily_2026-01-15_2026-01-15.html).
        bucket: Nombre del bucket S3 del Sitio_Reportes.
        s3_client: Cliente boto3 de S3 (opcional, se crea uno si no se provee).

    Returns:
        True si la publicación fue exitosa, False si falló después de los
        reintentos.
    """
    if s3_client is None:
        s3_client = boto3.client("s3")

    start_time = time.time()
    last_error: Optional[str] = None

    for attempt in range(1 + MAX_RETRIES):
        try:
            # Verificar que no hemos excedido el tiempo máximo de publicación
            elapsed = time.time() - start_time
            if elapsed >= MAX_PUBLISH_TIME_SECONDS:
                logger.error(
                    "Tiempo máximo de publicación excedido (%.1f s >= %d s). "
                    "Archivo: %s, Bucket: %s",
                    elapsed,
                    MAX_PUBLISH_TIME_SECONDS,
                    filename,
                    bucket,
                )
                return False

            s3_client.put_object(
                Bucket=bucket,
                Key=filename,
                Body=html_content.encode("utf-8"),
                ContentType="text/html",
            )

            elapsed = time.time() - start_time
            logger.info(
                "Reporte publicado exitosamente en %.2f s. "
                "Archivo: %s, Bucket: %s, Intento: %d",
                elapsed,
                filename,
                bucket,
                attempt + 1,
            )
            return True

        except ClientError as e:
            last_error = str(e)
            logger.warning(
                "Error al publicar reporte (intento %d/%d): %s. "
                "Archivo: %s, Bucket: %s",
                attempt + 1,
                1 + MAX_RETRIES,
                last_error,
                filename,
                bucket,
            )

            # Si aún quedan reintentos, esperar antes del siguiente intento
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)

    # Todos los reintentos agotados
    logger.error(
        "Publicación fallida después de %d intentos. "
        "Último error: %s. Archivo: %s, Bucket: %s. "
        "El pipeline continuará con notificación de fallo parcial.",
        1 + MAX_RETRIES,
        last_error,
        filename,
        bucket,
    )
    return False


def lambda_handler(event: dict, context=None) -> dict:
    """Handler Lambda para Step Functions — publica reporte en sitio web."""
    import os

    reports_bucket = os.environ["REPORTS_BUCKET"]
    site_prefix = os.environ.get("SITE_PREFIX", "site/")

    s3_client = boto3.client("s3")

    # Obtener info del reporte generado
    reports = event.get("reports", {}).get("Payload", {})
    if not reports:
        reports = event.get("reports", {})

    html_s3_key = reports.get("html_s3_key", "")
    if not html_s3_key:
        return {"published": False, "reason": "No HTML report to publish"}

    # Descargar HTML del bucket de reportes
    response = s3_client.get_object(Bucket=reports_bucket, Key=html_s3_key)
    html_content = response["Body"].read().decode("utf-8")

    # Publicar en sitio
    filename = site_prefix + html_s3_key.split("/")[-1]
    success = publish_report(html_content, filename, reports_bucket, s3_client)

    return {"published": success, "filename": filename}
