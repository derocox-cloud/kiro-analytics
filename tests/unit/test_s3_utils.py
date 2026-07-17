"""Tests unitarios para src/utils/s3_utils.py"""
from __future__ import annotations

import gzip
import io
import json

import boto3
import pytest
from moto import mock_aws

from src.utils.s3_utils import (
    download_csv,
    download_json_gz,
    paginated_list_objects,
    upload_json,
)

BUCKET = "test-bucket"


@pytest.fixture
def s3_client():
    """Crea un cliente S3 mock con un bucket de prueba."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


class TestPaginatedListObjects:
    """Tests para paginated_list_objects."""

    def test_empty_prefix(self, s3_client):
        """Retorna lista vacía si no hay objetos."""
        result = paginated_list_objects(s3_client, BUCKET, "nonexistent/")
        assert result == []

    def test_lists_objects_with_metadata(self, s3_client):
        """Retorna objetos con Key, Size y LastModified."""
        s3_client.put_object(Bucket=BUCKET, Key="data/file1.csv", Body=b"contenido")
        s3_client.put_object(Bucket=BUCKET, Key="data/file2.csv", Body=b"otro")

        result = paginated_list_objects(s3_client, BUCKET, "data/")
        assert len(result) == 2
        keys = [obj["Key"] for obj in result]
        assert "data/file1.csv" in keys
        assert "data/file2.csv" in keys
        # Verificar que tiene los campos esperados
        for obj in result:
            assert "Key" in obj
            assert "Size" in obj
            assert "LastModified" in obj

    def test_filters_by_prefix(self, s3_client):
        """Solo retorna objetos que coinciden con el prefijo."""
        s3_client.put_object(Bucket=BUCKET, Key="data/a.csv", Body=b"a")
        s3_client.put_object(Bucket=BUCKET, Key="other/b.csv", Body=b"b")

        result = paginated_list_objects(s3_client, BUCKET, "data/")
        assert len(result) == 1
        assert result[0]["Key"] == "data/a.csv"


class TestDownloadCsv:
    """Tests para download_csv."""

    def test_downloads_csv_content(self, s3_client):
        """Descarga y retorna contenido CSV como string."""
        csv_content = "col1,col2\nval1,val2\n"
        s3_client.put_object(Bucket=BUCKET, Key="test.csv", Body=csv_content.encode("utf-8"))

        result = download_csv(s3_client, BUCKET, "test.csv")
        assert result == csv_content

    def test_handles_utf8_encoding(self, s3_client):
        """Maneja correctamente caracteres UTF-8."""
        csv_content = "nombre,descripción\nJosé,análisis de código\n"
        s3_client.put_object(Bucket=BUCKET, Key="utf8.csv", Body=csv_content.encode("utf-8"))

        result = download_csv(s3_client, BUCKET, "utf8.csv")
        assert "José" in result
        assert "análisis" in result


class TestDownloadJsonGz:
    """Tests para download_json_gz."""

    def test_downloads_and_decompresses(self, s3_client):
        """Descarga, descomprime y parsea JSON gzipped."""
        data = {"key": "value", "number": 42}
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            gz.write(json.dumps(data).encode("utf-8"))
        s3_client.put_object(Bucket=BUCKET, Key="test.json.gz", Body=buf.getvalue())

        result = download_json_gz(s3_client, BUCKET, "test.json.gz")
        assert result == data

    def test_handles_nested_structures(self, s3_client):
        """Maneja estructuras JSON anidadas."""
        data = {"records": [{"id": 1, "nested": {"a": "b"}}]}
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            gz.write(json.dumps(data).encode("utf-8"))
        s3_client.put_object(Bucket=BUCKET, Key="nested.json.gz", Body=buf.getvalue())

        result = download_json_gz(s3_client, BUCKET, "nested.json.gz")
        assert result["records"][0]["nested"]["a"] == "b"


class TestUploadJson:
    """Tests para upload_json."""

    def test_uploads_json(self, s3_client):
        """Sube datos serializados como JSON."""
        data = {"users": [{"name": "test"}]}
        upload_json(s3_client, BUCKET, "output.json", data)

        # Verificar que se subió correctamente
        response = s3_client.get_object(Bucket=BUCKET, Key="output.json")
        content = json.loads(response["Body"].read().decode("utf-8"))
        assert content == data

    def test_handles_non_ascii(self, s3_client):
        """Maneja caracteres no-ASCII correctamente."""
        data = {"mensaje": "análisis completado", "usuario": "José"}
        upload_json(s3_client, BUCKET, "spanish.json", data)

        response = s3_client.get_object(Bucket=BUCKET, Key="spanish.json")
        content = json.loads(response["Body"].read().decode("utf-8"))
        assert content["mensaje"] == "análisis completado"

    def test_sets_content_type(self, s3_client):
        """Establece el Content-Type como application/json."""
        upload_json(s3_client, BUCKET, "typed.json", {"a": 1})

        # Moto no siempre preserva ContentType, pero verificamos que no falla
        response = s3_client.get_object(Bucket=BUCKET, Key="typed.json")
        assert response["ContentType"] == "application/json"
