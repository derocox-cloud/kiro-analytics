"""Utilidades de interacción con S3 para el pipeline de analytics."""
from __future__ import annotations

import csv
import gzip
import io
import json
from typing import Any, List


def paginated_list_objects(s3, bucket: str, prefix: str) -> List[dict]:
    """
    Lista todos los objetos bajo un prefijo S3 usando paginación.

    Maneja más de 1000 objetos usando el paginador de S3.
    Retorna lista de dicts con metadata de objetos (Key, Size, LastModified).
    """
    objects = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            objects.append({
                "Key": obj["Key"],
                "Size": obj.get("Size", 0),
                "LastModified": obj.get("LastModified"),
            })
    return objects


def download_csv(s3, bucket: str, key: str) -> str:
    """
    Descarga un archivo CSV de S3 y retorna su contenido como string UTF-8.
    """
    response = s3.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")
    return content


def download_json_gz(s3, bucket: str, key: str) -> dict:
    """
    Descarga un archivo JSON comprimido con gzip de S3, lo descomprime y retorna como dict.
    """
    response = s3.get_object(Bucket=bucket, Key=key)
    raw_bytes = response["Body"].read()
    with gzip.GzipFile(fileobj=io.BytesIO(raw_bytes)) as gz:
        decompressed = gz.read().decode("utf-8")
    return json.loads(decompressed)


def upload_json(s3, bucket: str, key: str, data: Any) -> None:
    """
    Serializa datos como JSON y los sube a S3.
    """
    body = json.dumps(data, ensure_ascii=False, default=str)
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )


def download_json(s3, bucket: str, key: str) -> Any:
    """Descarga un archivo JSON de S3 y retorna su contenido deserializado."""
    response = s3.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")
    return json.loads(content)
