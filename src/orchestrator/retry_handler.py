"""
Módulo de reintentos y manejo de errores para el orquestador del pipeline.

Implementa:
- Reintentos con backoff exponencial (5s, 10s, 20s) hasta 3 veces por etapa.
- Rastreo de estado de etapas (PENDING, RUNNING, SUCCEEDED, FAILED, RETRYING)
  con registro en CloudWatch usando timestamps ISO 8601.
- Timeout global de ejecución de 10 minutos.
- Fallo de etapa de recolección si cualquier Lambda paralela falla.

Requisitos: 1.2, 1.3, 2.6
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Intervalos de backoff por defecto (en segundos)
DEFAULT_BACKOFF_INTERVALS: List[int] = [5, 10, 20]

# Máximo de reintentos por defecto
DEFAULT_MAX_RETRIES: int = 3

# Timeout global de ejecución en segundos (10 minutos)
GLOBAL_TIMEOUT_SECONDS: int = 600

# Estados posibles de una etapa del pipeline
STAGE_PENDING = "PENDING"
STAGE_RUNNING = "RUNNING"
STAGE_SUCCEEDED = "SUCCEEDED"
STAGE_FAILED = "FAILED"
STAGE_RETRYING = "RETRYING"

VALID_STAGE_STATES = {
    STAGE_PENDING,
    STAGE_RUNNING,
    STAGE_SUCCEEDED,
    STAGE_FAILED,
    STAGE_RETRYING,
}


class TimeoutError(Exception):
    """Error lanzado cuando la ejecución global excede el timeout de 10 minutos."""

    pass


class StageTracker:
    """
    Rastreo de estado de etapas del pipeline con logging a CloudWatch.

    Registra cada transición de estado con timestamp ISO 8601 y duración
    en milisegundos desde el inicio de la etapa.
    """

    def __init__(self) -> None:
        """Inicializa el rastreador de etapas."""
        self._stages: Dict[str, Dict[str, Any]] = {}

    def register_stage(self, stage_name: str) -> None:
        """
        Registra una nueva etapa en estado PENDING.

        Args:
            stage_name: Nombre de la etapa a registrar.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        self._stages[stage_name] = {
            "state": STAGE_PENDING,
            "started_at": None,
            "last_transition": timestamp,
            "duration_ms": 0,
            "attempts": 0,
        }
        self._log_transition(stage_name, STAGE_PENDING, timestamp, 0)

    def transition(self, stage_name: str, new_state: str) -> None:
        """
        Realiza una transición de estado para una etapa.

        Registra el cambio en CloudWatch con timestamp ISO 8601 y duración
        acumulada en milisegundos.

        Args:
            stage_name: Nombre de la etapa.
            new_state: Nuevo estado (PENDING, RUNNING, SUCCEEDED, FAILED, RETRYING).

        Raises:
            ValueError: Si el estado no es válido o la etapa no está registrada.
        """
        if new_state not in VALID_STAGE_STATES:
            raise ValueError(
                f"Estado inválido '{new_state}'. "
                f"Estados válidos: {VALID_STAGE_STATES}"
            )

        if stage_name not in self._stages:
            raise ValueError(
                f"Etapa '{stage_name}' no registrada. "
                f"Use register_stage() primero."
            )

        timestamp = datetime.now(timezone.utc).isoformat()
        stage_info = self._stages[stage_name]

        # Calcular duración desde el inicio de la etapa
        if new_state == STAGE_RUNNING and stage_info["started_at"] is None:
            stage_info["started_at"] = time.time()

        if stage_info["started_at"] is not None:
            elapsed = time.time() - stage_info["started_at"]
            stage_info["duration_ms"] = int(elapsed * 1000)

        if new_state == STAGE_RETRYING:
            stage_info["attempts"] += 1

        stage_info["state"] = new_state
        stage_info["last_transition"] = timestamp

        self._log_transition(
            stage_name, new_state, timestamp, stage_info["duration_ms"]
        )

    def get_state(self, stage_name: str) -> Optional[str]:
        """
        Obtiene el estado actual de una etapa.

        Args:
            stage_name: Nombre de la etapa.

        Returns:
            Estado actual de la etapa, o None si no está registrada.
        """
        stage_info = self._stages.get(stage_name)
        if stage_info is None:
            return None
        return stage_info["state"]

    def get_duration_ms(self, stage_name: str) -> int:
        """
        Obtiene la duración acumulada de una etapa en milisegundos.

        Args:
            stage_name: Nombre de la etapa.

        Returns:
            Duración en milisegundos, o 0 si la etapa no existe.
        """
        stage_info = self._stages.get(stage_name)
        if stage_info is None:
            return 0
        return stage_info["duration_ms"]

    def get_attempts(self, stage_name: str) -> int:
        """
        Obtiene el número de intentos de reintento de una etapa.

        Args:
            stage_name: Nombre de la etapa.

        Returns:
            Número de reintentos realizados.
        """
        stage_info = self._stages.get(stage_name)
        if stage_info is None:
            return 0
        return stage_info["attempts"]

    def get_all_stages(self) -> Dict[str, Dict[str, Any]]:
        """
        Retorna información de todas las etapas registradas.

        Returns:
            Diccionario con info de cada etapa.
        """
        return dict(self._stages)

    def _log_transition(
        self,
        stage_name: str,
        state: str,
        timestamp: str,
        duration_ms: int,
    ) -> None:
        """
        Registra la transición de estado en CloudWatch (via logging).

        El formato estructurado permite que CloudWatch Logs indexe
        los campos para consultas y métricas.

        Args:
            stage_name: Nombre de la etapa.
            state: Nuevo estado.
            timestamp: Timestamp ISO 8601 de la transición.
            duration_ms: Duración acumulada en milisegundos.
        """
        logger.info(
            "StageTransition | stage=%s | state=%s | timestamp=%s | duration_ms=%d",
            stage_name,
            state,
            timestamp,
            duration_ms,
        )


class TimeoutGuard:
    """
    Guardián de timeout global para la ejecución del pipeline.

    Verifica que la ejecución total no exceda 10 minutos (600 segundos).
    """

    def __init__(
        self, timeout_seconds: int = GLOBAL_TIMEOUT_SECONDS
    ) -> None:
        """
        Inicializa el guardián de timeout.

        Args:
            timeout_seconds: Tiempo máximo de ejecución en segundos.
                             Por defecto 600 (10 minutos).
        """
        self._timeout_seconds = timeout_seconds
        self._start_time = time.time()

    @property
    def timeout_seconds(self) -> int:
        """Retorna el timeout configurado en segundos."""
        return self._timeout_seconds

    @property
    def start_time(self) -> float:
        """Retorna el timestamp de inicio."""
        return self._start_time

    def elapsed_seconds(self) -> float:
        """
        Calcula el tiempo transcurrido desde el inicio.

        Returns:
            Segundos transcurridos.
        """
        return time.time() - self._start_time

    def remaining_seconds(self) -> float:
        """
        Calcula el tiempo restante antes del timeout.

        Returns:
            Segundos restantes (puede ser negativo si ya expiró).
        """
        return self._timeout_seconds - self.elapsed_seconds()

    def is_expired(self) -> bool:
        """
        Verifica si el timeout ha expirado.

        Returns:
            True si el tiempo transcurrido excede el timeout.
        """
        return self.elapsed_seconds() >= self._timeout_seconds

    def check(self) -> None:
        """
        Verifica el timeout y lanza excepción si ha expirado.

        Raises:
            TimeoutError: Si la ejecución ha excedido el timeout global.
        """
        if self.is_expired():
            elapsed = self.elapsed_seconds()
            raise TimeoutError(
                f"Timeout global excedido: {elapsed:.1f}s transcurridos, "
                f"límite de {self._timeout_seconds}s (10 minutos)."
            )


def retry_with_backoff(
    fn: Callable[..., Any],
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_intervals: Optional[List[int]] = None,
    stage_name: str = "",
    stage_tracker: Optional[StageTracker] = None,
    timeout_guard: Optional[TimeoutGuard] = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
) -> Any:
    """
    Ejecuta una función con reintentos y backoff exponencial.

    Implementa la política de reintentos del pipeline:
    - Máximo 3 reintentos por defecto
    - Intervalos de backoff: 5s, 10s, 20s
    - Registra transiciones de estado en el StageTracker
    - Verifica timeout global antes de cada reintento

    Args:
        fn: Función a ejecutar (sin argumentos, usar lambda/partial para pasar args).
        max_retries: Número máximo de reintentos (default 3).
        backoff_intervals: Lista de intervalos de espera en segundos entre reintentos.
                          Default: [5, 10, 20].
        stage_name: Nombre de la etapa para tracking y logging.
        stage_tracker: Instancia de StageTracker para registrar transiciones.
        timeout_guard: Instancia de TimeoutGuard para verificar timeout global.
        sleep_fn: Función de sleep para testing (default: time.sleep).

    Returns:
        Resultado de la función ejecutada exitosamente.

    Raises:
        TimeoutError: Si el timeout global expira durante la ejecución.
        Exception: La última excepción si se agotan los reintentos.
    """
    if backoff_intervals is None:
        backoff_intervals = list(DEFAULT_BACKOFF_INTERVALS)

    if sleep_fn is None:
        sleep_fn = time.sleep

    # Registrar etapa y transicionar a RUNNING
    if stage_tracker and stage_name:
        if stage_tracker.get_state(stage_name) is None:
            stage_tracker.register_stage(stage_name)
        stage_tracker.transition(stage_name, STAGE_RUNNING)

    last_exception: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        # Verificar timeout global antes de cada intento
        if timeout_guard:
            timeout_guard.check()

        try:
            result = fn()

            # Éxito: marcar como SUCCEEDED
            if stage_tracker and stage_name:
                stage_tracker.transition(stage_name, STAGE_SUCCEEDED)

            return result

        except Exception as e:
            last_exception = e

            logger.warning(
                "Intento %d/%d fallido para etapa '%s': %s",
                attempt + 1,
                max_retries + 1,
                stage_name or "sin_nombre",
                str(e),
            )

            # Si es el último intento, no reintentar
            if attempt >= max_retries:
                break

            # Transicionar a RETRYING antes de esperar
            if stage_tracker and stage_name:
                stage_tracker.transition(stage_name, STAGE_RETRYING)

            # Calcular intervalo de backoff
            interval_index = min(attempt, len(backoff_intervals) - 1)
            wait_seconds = backoff_intervals[interval_index]

            # Verificar que el timeout no expire durante la espera
            if timeout_guard:
                remaining = timeout_guard.remaining_seconds()
                if remaining <= wait_seconds:
                    # Marcar como FAILED por timeout
                    if stage_tracker and stage_name:
                        stage_tracker.transition(stage_name, STAGE_FAILED)
                    raise TimeoutError(
                        f"Timeout global expiraría durante espera de reintento "
                        f"para etapa '{stage_name}': quedan {remaining:.1f}s, "
                        f"se necesitan {wait_seconds}s."
                    ) from e

            logger.info(
                "Esperando %ds antes del reintento %d para etapa '%s'.",
                wait_seconds,
                attempt + 2,
                stage_name or "sin_nombre",
            )
            sleep_fn(wait_seconds)

    # Se agotaron los reintentos: marcar como FAILED
    if stage_tracker and stage_name:
        stage_tracker.transition(stage_name, STAGE_FAILED)

    logger.error(
        "Etapa '%s' fallida después de %d intentos. Último error: %s",
        stage_name or "sin_nombre",
        max_retries + 1,
        str(last_exception),
    )

    raise last_exception  # type: ignore[misc]


def execute_parallel_collection_with_retry(
    collection_fns: Dict[str, Callable[..., Any]],
    stage_tracker: Optional[StageTracker] = None,
    timeout_guard: Optional[TimeoutGuard] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_intervals: Optional[List[int]] = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
) -> Dict[str, Any]:
    """
    Ejecuta funciones de recolección paralela con manejo de fallos.

    Si cualquier función falla después de agotar reintentos, marca toda
    la etapa de recolección como fallida (Requisito 2.6).

    Args:
        collection_fns: Diccionario {nombre_fuente: función_recolectora}.
        stage_tracker: Instancia de StageTracker para registro de estados.
        timeout_guard: Instancia de TimeoutGuard para timeout global.
        max_retries: Máximo de reintentos por función.
        backoff_intervals: Intervalos de backoff en segundos.
        sleep_fn: Función de sleep para testing.

    Returns:
        Diccionario {nombre_fuente: resultado} con los resultados exitosos.

    Raises:
        RuntimeError: Si alguna función paralela falla tras reintentos,
                      con indicación de que toda la etapa falló.
        TimeoutError: Si el timeout global expira.
    """
    if backoff_intervals is None:
        backoff_intervals = list(DEFAULT_BACKOFF_INTERVALS)

    # Registrar la etapa de recolección como un todo
    collection_stage = "recoleccion"
    if stage_tracker:
        if stage_tracker.get_state(collection_stage) is None:
            stage_tracker.register_stage(collection_stage)
        stage_tracker.transition(collection_stage, STAGE_RUNNING)

    results: Dict[str, Any] = {}
    failed_source: Optional[str] = None
    failed_error: Optional[Exception] = None

    for source_name, fn in collection_fns.items():
        # Verificar timeout global antes de cada fuente
        if timeout_guard:
            timeout_guard.check()

        sub_stage = f"recoleccion_{source_name}"

        try:
            result = retry_with_backoff(
                fn=fn,
                max_retries=max_retries,
                backoff_intervals=backoff_intervals,
                stage_name=sub_stage,
                stage_tracker=stage_tracker,
                timeout_guard=timeout_guard,
                sleep_fn=sleep_fn,
            )
            results[source_name] = result

        except Exception as e:
            # Si una Lambda paralela falla, marcar toda la etapa como fallida
            failed_source = source_name
            failed_error = e
            break

    if failed_source is not None:
        # Marcar etapa de recolección completa como FAILED
        if stage_tracker:
            stage_tracker.transition(collection_stage, STAGE_FAILED)

        raise RuntimeError(
            f"Etapa de recolección fallida: fallo en '{failed_source}' "
            f"después de {max_retries + 1} intentos. Error: {str(failed_error)}"
        ) from failed_error

    # Todas las fuentes completaron exitosamente
    if stage_tracker:
        stage_tracker.transition(collection_stage, STAGE_SUCCEEDED)

    return results
