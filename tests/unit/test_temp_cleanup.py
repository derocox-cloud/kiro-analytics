"""Tests unitarios para src/orchestrator/temp_cleanup.py"""
from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from src.orchestrator.temp_cleanup import cleanup_temp_data


@pytest.fixture
def s3_bucket():
    """Crea un bucket S3 mock para pruebas de limpieza temporal."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket_name = "kiro-analytics-temp-test"
        s3.create_bucket(Bucket=bucket_name)
        yield s3, bucket_name


class TestCleanupTempData:
    """Tests para cleanup_temp_data."""

    def test_elimina_objetos_con_prefijo_correcto(self, s3_bucket):
        """Elimina todos los objetos bajo tmp/{execution_id}/."""
        s3, bucket = s3_bucket
        execution_id = "exec-abc-123"

        # Crear objetos temporales
        for i in range(5):
            s3.put_object(
                Bucket=bucket,
                Key=f"tmp/{execution_id}/data_{i}.json",
                Body=b"test data",
            )

        deleted = cleanup_temp_data(s3, bucket, execution_id)

        assert deleted == 5

        # Verificar que no quedan objetos
        response = s3.list_objects_v2(
            Bucket=bucket, Prefix=f"tmp/{execution_id}/"
        )
        assert response.get("KeyCount", 0) == 0

    def test_no_elimina_objetos_de_otra_ejecucion(self, s3_bucket):
        """No afecta objetos de otras ejecuciones."""
        s3, bucket = s3_bucket
        target_id = "exec-target"
        other_id = "exec-other"

        # Crear objetos para dos ejecuciones
        s3.put_object(
            Bucket=bucket,
            Key=f"tmp/{target_id}/data.json",
            Body=b"target",
        )
        s3.put_object(
            Bucket=bucket,
            Key=f"tmp/{other_id}/data.json",
            Body=b"other",
        )

        cleanup_temp_data(s3, bucket, target_id)

        # Verificar que el objeto de la otra ejecución sigue presente
        response = s3.list_objects_v2(
            Bucket=bucket, Prefix=f"tmp/{other_id}/"
        )
        assert response.get("KeyCount", 0) == 1

    def test_bucket_vacio_retorna_cero(self, s3_bucket):
        """Si no hay objetos temporales, retorna 0 sin error."""
        s3, bucket = s3_bucket

        deleted = cleanup_temp_data(s3, bucket, "exec-inexistente")

        assert deleted == 0

    def test_maneja_error_s3_gracefully(self):
        """Si S3 lanza un error, registra warning y retorna 0 sin lanzar excepción."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            # No crear el bucket — provocará un error

            # No debe lanzar excepción
            deleted = cleanup_temp_data(s3, "bucket-no-existe", "exec-123")

            assert deleted == 0

    def test_maneja_muchos_objetos(self, s3_bucket):
        """Maneja correctamente la paginación con muchos objetos."""
        s3, bucket = s3_bucket
        execution_id = "exec-large"

        # Crear 15 objetos (más de lo típico pero verificable)
        for i in range(15):
            s3.put_object(
                Bucket=bucket,
                Key=f"tmp/{execution_id}/chunk_{i:03d}.json",
                Body=b"x" * 100,
            )

        deleted = cleanup_temp_data(s3, bucket, execution_id)

        assert deleted == 15

        # Verificar que no quedan objetos
        response = s3.list_objects_v2(
            Bucket=bucket, Prefix=f"tmp/{execution_id}/"
        )
        assert response.get("KeyCount", 0) == 0

    def test_execution_id_con_caracteres_especiales(self, s3_bucket):
        """Funciona con execution_id que contiene UUIDs estándar."""
        s3, bucket = s3_bucket
        execution_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        s3.put_object(
            Bucket=bucket,
            Key=f"tmp/{execution_id}/output.json",
            Body=b"result",
        )

        deleted = cleanup_temp_data(s3, bucket, execution_id)

        assert deleted == 1
