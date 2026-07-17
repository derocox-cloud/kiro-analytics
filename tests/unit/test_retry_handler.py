"""
Tests unitarios para el módulo de reintentos y manejo de errores.

Verifica:
- Intervalos de backoff correctos (5s, 10s, 20s)
- Máximo de reintentos respetado (3 intentos)
- Transiciones de estado registradas correctamente
- Detección de timeout (ejecución excede 10 minutos)
- Fallo de recolección paralela marca toda la etapa como fallida
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch, call

import pytest

from src.orchestrator.retry_handler import (
    DEFAULT_BACKOFF_INTERVALS,
    DEFAULT_MAX_RETRIES,
    GLOBAL_TIMEOUT_SECONDS,
    STAGE_FAILED,
    STAGE_PENDING,
    STAGE_RETRYING,
    STAGE_RUNNING,
    STAGE_SUCCEEDED,
    StageTracker,
    TimeoutError,
    TimeoutGuard,
    execute_parallel_collection_with_retry,
    retry_with_backoff,
)


class TestRetryWithBackoff:
    """Tests para la función retry_with_backoff."""

    def test_exito_en_primer_intento(self):
        """Retorna resultado si la función tiene éxito en el primer intento."""
        fn = MagicMock(return_value="resultado")

        result = retry_with_backoff(fn, stage_name="test_stage")

        assert result == "resultado"
        fn.assert_called_once()

    def test_exito_despues_de_reintentos(self):
        """Retorna resultado después de reintentos fallidos."""
        fn = MagicMock(side_effect=[ValueError("e1"), ValueError("e2"), "ok"])
        sleep_fn = MagicMock()

        result = retry_with_backoff(
            fn, stage_name="test_stage", sleep_fn=sleep_fn
        )

        assert result == "ok"
        assert fn.call_count == 3

    def test_backoff_intervalos_correctos(self):
        """Los intervalos de backoff son 5s, 10s, 20s."""
        fn = MagicMock(
            side_effect=[ValueError("e1"), ValueError("e2"), ValueError("e3"), "ok"]
        )
        sleep_fn = MagicMock()

        result = retry_with_backoff(
            fn, stage_name="test_stage", sleep_fn=sleep_fn
        )

        assert result == "ok"
        # Verifica intervalos: 5s después del 1er fallo, 10s después del 2do, 20s después del 3ro
        sleep_fn.assert_has_calls([call(5), call(10), call(20)])

    def test_max_reintentos_respetado(self):
        """Lanza excepción después de agotar 3 reintentos (4 intentos totales)."""
        fn = MagicMock(side_effect=ValueError("siempre falla"))
        sleep_fn = MagicMock()

        with pytest.raises(ValueError, match="siempre falla"):
            retry_with_backoff(
                fn,
                max_retries=3,
                stage_name="test_stage",
                sleep_fn=sleep_fn,
            )

        # 1 intento inicial + 3 reintentos = 4 llamadas
        assert fn.call_count == 4
        # 3 sleeps entre los intentos
        assert sleep_fn.call_count == 3

    def test_cero_reintentos_falla_inmediato(self):
        """Con max_retries=0 no reintenta y falla en el primer error."""
        fn = MagicMock(side_effect=RuntimeError("fallo"))
        sleep_fn = MagicMock()

        with pytest.raises(RuntimeError, match="fallo"):
            retry_with_backoff(
                fn, max_retries=0, stage_name="test", sleep_fn=sleep_fn
            )

        fn.assert_called_once()
        sleep_fn.assert_not_called()

    def test_backoff_custom_intervals(self):
        """Soporta intervalos de backoff personalizados."""
        fn = MagicMock(side_effect=[ValueError("e"), "ok"])
        sleep_fn = MagicMock()

        result = retry_with_backoff(
            fn,
            backoff_intervals=[2, 4, 8],
            stage_name="test",
            sleep_fn=sleep_fn,
        )

        assert result == "ok"
        sleep_fn.assert_called_once_with(2)

    def test_stage_tracker_transiciones(self):
        """Registra transiciones RUNNING → SUCCEEDED en el StageTracker."""
        fn = MagicMock(return_value="ok")
        tracker = StageTracker()

        retry_with_backoff(
            fn, stage_name="mi_etapa", stage_tracker=tracker
        )

        assert tracker.get_state("mi_etapa") == STAGE_SUCCEEDED

    def test_stage_tracker_con_reintentos(self):
        """Registra transiciones RUNNING → RETRYING → ... → SUCCEEDED."""
        fn = MagicMock(side_effect=[ValueError("e"), "ok"])
        tracker = StageTracker()
        sleep_fn = MagicMock()

        retry_with_backoff(
            fn,
            stage_name="mi_etapa",
            stage_tracker=tracker,
            sleep_fn=sleep_fn,
        )

        assert tracker.get_state("mi_etapa") == STAGE_SUCCEEDED
        assert tracker.get_attempts("mi_etapa") == 1

    def test_stage_tracker_fallo_total(self):
        """Registra transición a FAILED cuando se agotan los reintentos."""
        fn = MagicMock(side_effect=ValueError("siempre falla"))
        tracker = StageTracker()
        sleep_fn = MagicMock()

        with pytest.raises(ValueError):
            retry_with_backoff(
                fn,
                stage_name="etapa_fallo",
                stage_tracker=tracker,
                sleep_fn=sleep_fn,
            )

        assert tracker.get_state("etapa_fallo") == STAGE_FAILED

    def test_timeout_guard_antes_de_intento(self):
        """Lanza TimeoutError si el timeout ha expirado antes de ejecutar."""
        fn = MagicMock(return_value="ok")
        timeout_guard = TimeoutGuard(timeout_seconds=0)
        # Forzar que el tiempo transcurrido sea mayor al timeout
        timeout_guard._start_time = time.time() - 1

        with pytest.raises(TimeoutError):
            retry_with_backoff(
                fn,
                stage_name="test",
                timeout_guard=timeout_guard,
            )

    def test_timeout_guard_durante_espera_backoff(self):
        """Lanza TimeoutError si el timeout expiraría durante la espera de backoff."""
        fn = MagicMock(side_effect=ValueError("fallo"))
        sleep_fn = MagicMock()

        # Timeout con solo 2 segundos restantes (el primer backoff es 5s)
        timeout_guard = TimeoutGuard(timeout_seconds=2)

        with pytest.raises(TimeoutError):
            retry_with_backoff(
                fn,
                stage_name="test",
                timeout_guard=timeout_guard,
                sleep_fn=sleep_fn,
            )

        # No debería haber dormido porque el timeout expiraría
        sleep_fn.assert_not_called()


class TestStageTracker:
    """Tests para la clase StageTracker."""

    def test_registro_etapa_estado_pending(self):
        """Una etapa recién registrada comienza en estado PENDING."""
        tracker = StageTracker()
        tracker.register_stage("lectura_roster")

        assert tracker.get_state("lectura_roster") == STAGE_PENDING

    def test_transicion_a_running(self):
        """Puede transicionar de PENDING a RUNNING."""
        tracker = StageTracker()
        tracker.register_stage("procesamiento")
        tracker.transition("procesamiento", STAGE_RUNNING)

        assert tracker.get_state("procesamiento") == STAGE_RUNNING

    def test_transicion_a_succeeded(self):
        """Puede transicionar a SUCCEEDED."""
        tracker = StageTracker()
        tracker.register_stage("test")
        tracker.transition("test", STAGE_RUNNING)
        tracker.transition("test", STAGE_SUCCEEDED)

        assert tracker.get_state("test") == STAGE_SUCCEEDED

    def test_transicion_a_failed(self):
        """Puede transicionar a FAILED."""
        tracker = StageTracker()
        tracker.register_stage("test")
        tracker.transition("test", STAGE_RUNNING)
        tracker.transition("test", STAGE_FAILED)

        assert tracker.get_state("test") == STAGE_FAILED

    def test_transicion_a_retrying_incrementa_intentos(self):
        """La transición a RETRYING incrementa el contador de intentos."""
        tracker = StageTracker()
        tracker.register_stage("test")
        tracker.transition("test", STAGE_RUNNING)
        tracker.transition("test", STAGE_RETRYING)
        tracker.transition("test", STAGE_RETRYING)

        assert tracker.get_attempts("test") == 2

    def test_estado_invalido_lanza_error(self):
        """Lanza ValueError para estados no válidos."""
        tracker = StageTracker()
        tracker.register_stage("test")

        with pytest.raises(ValueError, match="Estado inválido"):
            tracker.transition("test", "INVALID_STATE")

    def test_etapa_no_registrada_lanza_error(self):
        """Lanza ValueError si la etapa no ha sido registrada."""
        tracker = StageTracker()

        with pytest.raises(ValueError, match="no registrada"):
            tracker.transition("no_existe", STAGE_RUNNING)

    def test_get_state_etapa_inexistente(self):
        """Retorna None para una etapa no registrada."""
        tracker = StageTracker()
        assert tracker.get_state("no_existe") is None

    def test_duracion_ms_calculada(self):
        """Calcula la duración en milisegundos desde el inicio de la etapa."""
        tracker = StageTracker()
        tracker.register_stage("test")
        tracker.transition("test", STAGE_RUNNING)

        # Simular paso de tiempo mínimo
        time.sleep(0.01)  # 10ms
        tracker.transition("test", STAGE_SUCCEEDED)

        duration = tracker.get_duration_ms("test")
        assert duration >= 10  # Al menos 10ms

    def test_get_all_stages(self):
        """Retorna información de todas las etapas registradas."""
        tracker = StageTracker()
        tracker.register_stage("etapa1")
        tracker.register_stage("etapa2")

        all_stages = tracker.get_all_stages()

        assert "etapa1" in all_stages
        assert "etapa2" in all_stages
        assert all_stages["etapa1"]["state"] == STAGE_PENDING
        assert all_stages["etapa2"]["state"] == STAGE_PENDING

    def test_log_transition_formato_cloudwatch(self, caplog):
        """Las transiciones se registran con formato adecuado para CloudWatch."""
        import logging

        with caplog.at_level(logging.INFO):
            tracker = StageTracker()
            tracker.register_stage("mi_etapa")
            tracker.transition("mi_etapa", STAGE_RUNNING)

        # Verificar que el log contiene los campos estructurados
        assert any("StageTransition" in record.message for record in caplog.records)
        assert any("stage=mi_etapa" in record.message for record in caplog.records)
        assert any("state=RUNNING" in record.message for record in caplog.records)
        assert any("timestamp=" in record.message for record in caplog.records)
        assert any("duration_ms=" in record.message for record in caplog.records)


class TestTimeoutGuard:
    """Tests para la clase TimeoutGuard."""

    def test_timeout_por_defecto_10_minutos(self):
        """El timeout por defecto es 600 segundos (10 minutos)."""
        guard = TimeoutGuard()
        assert guard.timeout_seconds == 600

    def test_timeout_custom(self):
        """Acepta timeout personalizado."""
        guard = TimeoutGuard(timeout_seconds=120)
        assert guard.timeout_seconds == 120

    def test_no_expirado_al_inicio(self):
        """No está expirado inmediatamente después de crear."""
        guard = TimeoutGuard(timeout_seconds=600)
        assert guard.is_expired() is False

    def test_expirado_despues_de_timeout(self):
        """Está expirado si el tiempo transcurrido excede el timeout."""
        guard = TimeoutGuard(timeout_seconds=1)
        # Forzar que haya pasado más del timeout
        guard._start_time = time.time() - 2

        assert guard.is_expired() is True

    def test_check_no_lanza_si_no_expirado(self):
        """check() no lanza excepción si no ha expirado."""
        guard = TimeoutGuard(timeout_seconds=600)
        guard.check()  # No debería lanzar

    def test_check_lanza_timeout_error_si_expirado(self):
        """check() lanza TimeoutError si ha expirado."""
        guard = TimeoutGuard(timeout_seconds=1)
        guard._start_time = time.time() - 2

        with pytest.raises(TimeoutError, match="Timeout global excedido"):
            guard.check()

    def test_elapsed_seconds(self):
        """elapsed_seconds() retorna el tiempo transcurrido."""
        guard = TimeoutGuard(timeout_seconds=600)
        guard._start_time = time.time() - 5

        elapsed = guard.elapsed_seconds()
        assert 4.9 <= elapsed <= 6.0

    def test_remaining_seconds(self):
        """remaining_seconds() retorna el tiempo restante."""
        guard = TimeoutGuard(timeout_seconds=600)
        guard._start_time = time.time() - 100

        remaining = guard.remaining_seconds()
        assert 499 <= remaining <= 501

    def test_remaining_negativo_cuando_expirado(self):
        """remaining_seconds() puede ser negativo si ya expiró."""
        guard = TimeoutGuard(timeout_seconds=10)
        guard._start_time = time.time() - 15

        assert guard.remaining_seconds() < 0


class TestExecuteParallelCollectionWithRetry:
    """Tests para la ejecución de recolección paralela con reintentos."""

    def test_todas_fuentes_exitosas(self):
        """Retorna resultados de todas las fuentes si todas tienen éxito."""
        fns = {
            "user_report": MagicMock(return_value="data_ur"),
            "analytics": MagicMock(return_value="data_an"),
            "prompts": MagicMock(return_value="data_pr"),
        }

        results = execute_parallel_collection_with_retry(
            collection_fns=fns, sleep_fn=MagicMock()
        )

        assert results == {
            "user_report": "data_ur",
            "analytics": "data_an",
            "prompts": "data_pr",
        }

    def test_una_fuente_falla_marca_etapa_completa_fallida(self):
        """Si una fuente falla, toda la etapa de recolección se marca como fallida."""
        fns = {
            "user_report": MagicMock(return_value="ok"),
            "analytics": MagicMock(side_effect=RuntimeError("S3 error")),
            "prompts": MagicMock(return_value="ok"),
        }
        tracker = StageTracker()
        sleep_fn = MagicMock()

        with pytest.raises(RuntimeError, match="Etapa de recolección fallida"):
            execute_parallel_collection_with_retry(
                collection_fns=fns,
                stage_tracker=tracker,
                sleep_fn=sleep_fn,
            )

        # La etapa de recolección global debe estar en FAILED
        assert tracker.get_state("recoleccion") == STAGE_FAILED

    def test_fuente_falla_despues_de_reintentos(self):
        """La fuente que falla agota sus reintentos antes de fallar la etapa."""
        fns = {
            "user_report": MagicMock(side_effect=ValueError("siempre falla")),
        }
        sleep_fn = MagicMock()

        with pytest.raises(RuntimeError, match="Etapa de recolección fallida"):
            execute_parallel_collection_with_retry(
                collection_fns=fns,
                max_retries=3,
                sleep_fn=sleep_fn,
            )

        # Debería haberse intentado 4 veces (1 + 3 reintentos)
        assert fns["user_report"].call_count == 4

    def test_tracker_registra_succeeded_cuando_todo_ok(self):
        """El StageTracker registra SUCCEEDED para la etapa de recolección completa."""
        fns = {
            "source_a": MagicMock(return_value="data_a"),
            "source_b": MagicMock(return_value="data_b"),
        }
        tracker = StageTracker()

        execute_parallel_collection_with_retry(
            collection_fns=fns,
            stage_tracker=tracker,
            sleep_fn=MagicMock(),
        )

        assert tracker.get_state("recoleccion") == STAGE_SUCCEEDED

    def test_timeout_durante_recoleccion(self):
        """Lanza TimeoutError si el timeout global expira durante la recolección."""
        fns = {
            "source_a": MagicMock(return_value="ok"),
        }
        timeout_guard = TimeoutGuard(timeout_seconds=1)
        timeout_guard._start_time = time.time() - 2  # Ya expirado

        with pytest.raises(TimeoutError):
            execute_parallel_collection_with_retry(
                collection_fns=fns,
                timeout_guard=timeout_guard,
                sleep_fn=MagicMock(),
            )


class TestConstantesDefecto:
    """Tests para las constantes por defecto del módulo."""

    def test_backoff_intervals_por_defecto(self):
        """Los intervalos de backoff por defecto son [5, 10, 20]."""
        assert DEFAULT_BACKOFF_INTERVALS == [5, 10, 20]

    def test_max_retries_por_defecto(self):
        """El máximo de reintentos por defecto es 3."""
        assert DEFAULT_MAX_RETRIES == 3

    def test_timeout_global_10_minutos(self):
        """El timeout global es 600 segundos (10 minutos)."""
        assert GLOBAL_TIMEOUT_SECONDS == 600
