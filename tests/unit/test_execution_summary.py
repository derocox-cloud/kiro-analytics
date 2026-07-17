"""Tests unitarios para src/utils/execution_summary.py"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.models import ExecutionResult
from src.utils.execution_summary import build_execution_summary


class TestBuildExecutionSummary:
    """Tests para build_execution_summary."""

    def test_ejecucion_exitosa_contiene_todos_los_campos(self):
        """Un resultado exitoso genera resumen con todos los campos requeridos."""
        result = ExecutionResult(
            execution_id="exec-123",
            period="daily",
            reference_date="2026-05-15",
            status="SUCCEEDED",
            total_duration_seconds=120.5,
            stage_durations={"recoleccion": 30.0, "procesamiento": 50.2, "generacion": 40.3},
            users_processed=25,
            data_size_bytes=1024000,
            timestamp="2026-05-16T07:00:00+00:00",
        )

        summary = build_execution_summary(result)

        assert summary["periodo"] == "daily"
        assert summary["fecha_referencia"] == "2026-05-15"
        assert summary["estado"] == "SUCCEEDED"
        assert summary["duracion_total"] == 120.5
        assert summary["duracion_por_etapa"] == {
            "recoleccion": 30.0,
            "procesamiento": 50.2,
            "generacion": 40.3,
        }
        assert summary["usuarios_procesados"] == 25
        assert summary["etapa_fallo"] is None
        assert summary["timestamp"] == "2026-05-16T07:00:00+00:00"

    def test_ejecucion_fallida_incluye_etapa_fallo(self):
        """Un resultado fallido incluye la etapa de fallo."""
        result = ExecutionResult(
            execution_id="exec-456",
            period="weekly",
            reference_date="2026-05-11",
            status="FAILED",
            total_duration_seconds=45.0,
            stage_durations={"recoleccion": 45.0},
            users_processed=0,
            failure_stage="recoleccion",
            failure_message="S3 timeout",
            timestamp="2026-05-12T07:01:30+00:00",
        )

        summary = build_execution_summary(result)

        assert summary["estado"] == "FAILED"
        assert summary["etapa_fallo"] == "recoleccion"
        assert summary["usuarios_procesados"] == 0

    def test_timestamp_se_genera_si_no_existe(self):
        """Si el resultado no tiene timestamp, se genera uno ISO 8601."""
        result = ExecutionResult(
            execution_id="exec-789",
            period="monthly",
            reference_date="2026-05-01",
            status="SUCCEEDED",
            total_duration_seconds=200.0,
            users_processed=30,
            timestamp="",
        )

        summary = build_execution_summary(result)

        # Verificar que el timestamp generado es ISO 8601 válido
        parsed = datetime.fromisoformat(summary["timestamp"])
        assert parsed.tzinfo is not None

    def test_duracion_por_etapa_vacia(self):
        """Si no hay duraciones por etapa, retorna diccionario vacío."""
        result = ExecutionResult(
            execution_id="exec-000",
            period="daily",
            reference_date="2026-05-15",
            status="SUCCEEDED",
            total_duration_seconds=0.0,
            users_processed=0,
            timestamp="2026-05-15T08:00:00Z",
        )

        summary = build_execution_summary(result)

        assert summary["duracion_por_etapa"] == {}
        assert summary["duracion_total"] == 0.0

    def test_periodo_mensual(self):
        """Verifica que el periodo monthly se mapea correctamente."""
        result = ExecutionResult(
            execution_id="exec-monthly",
            period="monthly",
            reference_date="2026-04-01",
            status="SUCCEEDED",
            total_duration_seconds=300.0,
            stage_durations={
                "recoleccion": 60.0,
                "procesamiento": 100.0,
                "analisis_ai": 80.0,
                "generacion": 60.0,
            },
            users_processed=50,
            timestamp="2026-05-01T07:00:00-05:00",
        )

        summary = build_execution_summary(result)

        assert summary["periodo"] == "monthly"
        assert summary["fecha_referencia"] == "2026-04-01"
        assert len(summary["duracion_por_etapa"]) == 4

    def test_retorna_exactamente_ocho_campos(self):
        """El resumen siempre contiene exactamente los 8 campos requeridos."""
        result = ExecutionResult(
            execution_id="exec-count",
            period="daily",
            reference_date="2026-06-01",
            status="SUCCEEDED",
            total_duration_seconds=10.0,
            users_processed=5,
            timestamp="2026-06-01T12:00:00Z",
        )

        summary = build_execution_summary(result)

        campos_requeridos = {
            "periodo",
            "fecha_referencia",
            "estado",
            "duracion_total",
            "duracion_por_etapa",
            "usuarios_procesados",
            "etapa_fallo",
            "timestamp",
        }
        assert set(summary.keys()) == campos_requeridos
