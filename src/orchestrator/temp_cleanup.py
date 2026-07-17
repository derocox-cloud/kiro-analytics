"""
Módulo de limpieza de datos temporales en S3.

Elimina los objetos temporales generados durante la ejecución del pipeline,
identificados por el prefijo `tmp/{execution_id}/` en el bucket temporal.
La limpieza se realiza de forma tolerante a fallos para no afectar
el resultado del pipeline.
"""
from __future__ import annotations

import logging

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def cleanup_temp_data(
    s3_client,
    bucket: str,
    execution_id: str,
) -> int:
    """
    Elimina todos los objetos temporales asociados a una ejecución del pipeline.

    Busca y elimina objetos con el prefijo `tmp/{execution_id}/` en el bucket
    especificado. Maneja paginación para ejecuciones con muchos objetos temporales.
    Continúa de forma elegante si la limpieza falla (registra warning pero no lanza
    excepción).

    Args:
        s3_client: Cliente boto3 de S3.
        bucket: Nombre del bucket temporal.
        execution_id: Identificador único de la ejecución cuyos datos se limpian.

    Returns:
        Número de objetos eliminados. Retorna 0 si no había objetos o si hubo error.
    """
    prefix = f"tmp/{execution_id}/"
    total_deleted = 0

    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix)

        for page in page_iterator:
            contents = page.get("Contents", [])
            if not contents:
                continue

            # Preparar lote de objetos a eliminar
            objects_to_delete = [{"Key": obj["Key"]} for obj in contents]

            # Eliminar lote (máximo 1000 objetos por llamada de delete_objects)
            response = s3_client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": objects_to_delete, "Quiet": True},
            )

            # Contar errores si los hay
            errors = response.get("Errors", [])
            deleted_count = len(objects_to_delete) - len(errors)
            total_deleted += deleted_count

            if errors:
                logger.warning(
                    "Errores al eliminar %d objetos temporales: %s",
                    len(errors),
                    errors[:3],  # Mostrar máximo 3 errores para no saturar logs
                )

        if total_deleted > 0:
            logger.info(
                "Limpieza completada: %d objetos eliminados del prefijo '%s' "
                "en bucket '%s'",
                total_deleted,
                prefix,
                bucket,
            )
        else:
            logger.info(
                "No se encontraron objetos temporales para limpiar en '%s%s'",
                bucket,
                prefix,
            )

        return total_deleted

    except ClientError as e:
        logger.warning(
            "Error de S3 durante limpieza de datos temporales "
            "(execution_id=%s, bucket=%s): %s. Continuando sin limpiar.",
            execution_id,
            bucket,
            str(e),
        )
        return 0

    except Exception as e:
        logger.warning(
            "Error inesperado durante limpieza de datos temporales "
            "(execution_id=%s): %s. Continuando sin limpiar.",
            execution_id,
            str(e),
        )
        return 0
