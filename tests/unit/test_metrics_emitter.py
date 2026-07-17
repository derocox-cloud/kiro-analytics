"""Tests unitarios para src/orchestrator/metrics_emitter.py"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.models import ExecutionResult
from src.orchestrator.metrics_emitter import (
    METRICS_NAMESPACE,
    emit_pipeline_metrics,
)


class TestEmitPipelineMetrics:
    """Tests para emit_pipeline_metrics."""

    def _make_execution_result(self, **overrides) -> ExecutionResult:
        """Helper para crear un ExecutionResult con valores por defecto."""
        defaults = {
            "execution_id": "exec-test-001",
            "period": "daily",
            "reference_date": "2026-05-15",
            "status": "SUCCEEDED",
            "total_duration_seconds": 120.5,
            "stage_durations": {
                "recoleccion": 30.0,
                "procesamiento": 50.2,
                "generacion_reportes": 40.3,
            },
            "users_processed": 25,
            "data_size_bytes": 1024000,
            "timestamp": "2026-05-16T07:00:00+00:00",
        }
        defaults.update(overrides)
        return ExecutionResult(**defaults)

    def test_emite_metrica_total_duration(self):
        """Verifica que se emite TotalDuration con valor correcto."""
        mock_cw = MagicMock()
        result = self._make_execution_result(total_duration_seconds=95.7)

        emit_pipeline_metrics(result, cloudwatch_client=mock_cw)

        call_args = mock_cw.put_metric_data.call_args
        metric_data = call_args[1]["MetricData"]

        total_duration_metrics = [
            m for m in metric_data if m["MetricName"] == "TotalDuration"
        ]
        assert len(total_duration_metrics) == 1
        assert total_duration_metrics[0]["Value"] == 95.7
        assert total_duration_metrics[0]["Unit"] == "Seconds"

    def test_emite_metrica_users_processed(self):
        """Verifica que se emite UsersProcessed con valor correcto."""
        mock_cw = MagicMock()
        result = self._make_execution_result(users_processed=42)

        emit_pipeline_metrics(result, cloudwatch_client=mock_cw)

        call_args = mock_cw.put_metric_data.call_args
        metric_data = call_args[1]["MetricData"]

        users_metrics = [
            m for m in metric_data if m["MetricName"] == "UsersProcessed"
        ]
        assert len(users_metrics) == 1
        assert users_metrics[0]["Value"] == 42.0
        assert users_metrics[0]["Unit"] == "Count"

    def test_emite_metrica_data_collected_size(self):
        """Verifica que se emite DataCollectedSize con valor correcto."""
        mock_cw = MagicMock()
        result = self._make_execution_result(data_size_bytes=5_000_000)

        emit_pipeline_metrics(result, cloudwatch_client=mock_cw)

        call_args = mock_cw.put_metric_data.call_args
        metric_data = call_args[1]["MetricData"]

        size_metrics = [
            m for m in metric_data if m["MetricName"] == "DataCollectedSize"
        ]
        assert len(size_metrics) == 1
        assert size_metrics[0]["Value"] == 5_000_000.0
        assert size_metrics[0]["Unit"] == "Bytes"

    def test_emite_stage_duration_por_cada_etapa(self):
        """Verifica que se emite una métrica StageDuration por cada etapa."""
        mock_cw = MagicMock()
        stage_durations = {
            "recoleccion": 30.0,
            "procesamiento": 50.0,
            "analisis_ai": 20.0,
        }
        result = self._make_execution_result(stage_durations=stage_durations)

        emit_pipeline_metrics(result, cloudwatch_client=mock_cw)

        call_args = mock_cw.put_metric_data.call_args
        metric_data = call_args[1]["MetricData"]

        stage_metrics = [
            m for m in metric_data if m["MetricName"] == "StageDuration"
        ]
        assert len(stage_metrics) == 3

        # Verificar que cada etapa tiene su dimensión StageName
        stage_names = set()
        for m in stage_metrics:
            dims = {d["Name"]: d["Value"] for d in m["Dimensions"]}
            stage_names.add(dims["StageName"])
            assert dims["Period"] == "daily"
            assert m["Unit"] == "Seconds"

        assert stage_names == {"recoleccion", "procesamiento", "analisis_ai"}

    def test_dimension_period_correcta(self):
        """Verifica que todas las métricas incluyen la dimensión Period correcta."""
        mock_cw = MagicMock()
        result = self._make_execution_result(period="weekly")

        emit_pipeline_metrics(result, cloudwatch_client=mock_cw)

        call_args = mock_cw.put_metric_data.call_args
        metric_data = call_args[1]["MetricData"]

        for metric in metric_data:
            dims = {d["Name"]: d["Value"] for d in metric["Dimensions"]}
            assert dims["Period"] == "weekly"

    def test_namespace_correcto(self):
        """Verifica que se usa el namespace KiroAnalytics/Pipeline."""
        mock_cw = MagicMock()
        result = self._make_execution_result()

        emit_pipeline_metrics(result, cloudwatch_client=mock_cw)

        call_args = mock_cw.put_metric_data.call_args
        assert call_args[1]["Namespace"] == METRICS_NAMESPACE

    def test_sin_stage_durations_emite_metricas_base(self):
        """Si no hay etapas, solo emite TotalDuration, UsersProcessed y DataCollectedSize."""
        mock_cw = MagicMock()
        result = self._make_execution_result(stage_durations={})

        emit_pipeline_metrics(result, cloudwatch_client=mock_cw)

        call_args = mock_cw.put_metric_data.call_args
        metric_data = call_args[1]["MetricData"]

        # Solo 3 métricas: TotalDuration, UsersProcessed, DataCollectedSize
        assert len(metric_data) == 3
        metric_names = {m["MetricName"] for m in metric_data}
        assert metric_names == {"TotalDuration", "UsersProcessed", "DataCollectedSize"}

    def test_retorna_true_en_exito(self):
        """Retorna True cuando las métricas se emiten correctamente."""
        mock_cw = MagicMock()
        result = self._make_execution_result()

        success = emit_pipeline_metrics(result, cloudwatch_client=mock_cw)

        assert success is True

    def test_retorna_false_en_error(self):
        """Retorna False cuando CloudWatch lanza una excepción."""
        mock_cw = MagicMock()
        mock_cw.put_metric_data.side_effect = Exception("CloudWatch error")
        result = self._make_execution_result()

        success = emit_pipeline_metrics(result, cloudwatch_client=mock_cw)

        assert success is False

    def test_una_sola_llamada_put_metric_data_para_pocas_metricas(self):
        """Si las métricas caben en una llamada, solo se hace una invocación."""
        mock_cw = MagicMock()
        result = self._make_execution_result()

        emit_pipeline_metrics(result, cloudwatch_client=mock_cw)

        assert mock_cw.put_metric_data.call_count == 1
