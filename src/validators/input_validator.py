"""
Validador de parámetros de entrada del pipeline de analytics.

Valida que los parámetros de ejecución del pipeline cumplan con los
formatos y valores esperados antes de iniciar el procesamiento.
"""
from __future__ import annotations

from datetime import datetime

from src.models import PipelineInput, ValidationResult, VALID_PERIODS


# Formatos de salida válidos para los reportes
VALID_OUTPUT_FORMATS = ["html", "csv", "both"]


def validate_input(event: dict) -> ValidationResult:
    """
    Valida los parámetros de entrada del pipeline.

    Verifica que el evento contenga parámetros válidos para la ejecución:
    - period: debe ser "daily", "weekly" o "monthly"
    - reference_date: debe tener formato YYYY-MM-DD y ser una fecha calendario válida
    - ai_analysis: booleano (default True)
    - output_format: "html", "csv" o "both" (default "both")

    Args:
        event: Diccionario con los parámetros de ejecución del pipeline.

    Returns:
        ValidationResult con parámetros normalizados si es válido,
        o con mensaje de error descriptivo si es inválido.
    """
    # Validar que event sea un diccionario
    if not isinstance(event, dict):
        return ValidationResult(
            valid=False,
            error="El evento de entrada debe ser un diccionario.",
        )

    # Validar period
    period = event.get("period")
    if period is None:
        return ValidationResult(
            valid=False,
            error=(
                "El parámetro 'period' es requerido. "
                "Valores válidos: daily, weekly, monthly."
            ),
        )
    if period not in VALID_PERIODS:
        return ValidationResult(
            valid=False,
            error=(
                f"El parámetro 'period' tiene un valor inválido: '{period}'. "
                f"Valores válidos: {', '.join(VALID_PERIODS)}."
            ),
        )

    # Validar reference_date
    reference_date = event.get("reference_date")
    if reference_date is None:
        return ValidationResult(
            valid=False,
            error=(
                "El parámetro 'reference_date' es requerido. "
                "Formato esperado: YYYY-MM-DD (ejemplo: 2026-05-15)."
            ),
        )
    if not isinstance(reference_date, str):
        return ValidationResult(
            valid=False,
            error=(
                "El parámetro 'reference_date' debe ser una cadena de texto. "
                "Formato esperado: YYYY-MM-DD (ejemplo: 2026-05-15)."
            ),
        )
    # Verificar formato y validez de la fecha
    error_fecha = _validar_fecha(reference_date)
    if error_fecha is not None:
        return ValidationResult(valid=False, error=error_fecha)

    # Validar ai_analysis (opcional, default True)
    ai_analysis = event.get("ai_analysis", True)
    if not isinstance(ai_analysis, bool):
        return ValidationResult(
            valid=False,
            error=(
                f"El parámetro 'ai_analysis' debe ser un booleano (true/false). "
                f"Valor recibido: {ai_analysis!r}."
            ),
        )

    # Validar output_format (opcional, default "both")
    output_format = event.get("output_format", "both")
    if output_format not in VALID_OUTPUT_FORMATS:
        return ValidationResult(
            valid=False,
            error=(
                f"El parámetro 'output_format' tiene un valor inválido: '{output_format}'. "
                f"Valores válidos: {', '.join(VALID_OUTPUT_FORMATS)}."
            ),
        )

    # Todos los parámetros son válidos — construir PipelineInput normalizado
    params = PipelineInput(
        period=period,
        reference_date=reference_date,
        ai_analysis=ai_analysis,
        output_format=output_format,
    )

    return ValidationResult(valid=True, params=params)


def _validar_fecha(fecha_str: str) -> str | None:
    """
    Valida que una cadena tenga formato YYYY-MM-DD y sea una fecha calendario válida.

    Args:
        fecha_str: Cadena con la fecha a validar.

    Returns:
        None si la fecha es válida, o un mensaje de error descriptivo si no lo es.
    """
    try:
        datetime.strptime(fecha_str, "%Y-%m-%d")
    except ValueError:
        return (
            f"El parámetro 'reference_date' tiene un formato inválido: '{fecha_str}'. "
            "Formato esperado: YYYY-MM-DD (ejemplo: 2026-05-15). "
            "La fecha debe ser una fecha calendario válida."
        )
    return None


def lambda_handler(event: dict, context=None) -> dict:
    """Handler Lambda para Step Functions — valida parámetros de entrada."""
    from datetime import date as date_type

    from src.utils.date_utils import calculate_schedule_params

    # Si viene de EventBridge con schedule_type, calcular period y reference_date
    if "schedule_type" in event and "period" not in event:
        params = calculate_schedule_params(
            event["schedule_type"], date_type.today()
        )
        event = {
            "period": params.period,
            "reference_date": params.reference_date,
            "ai_analysis": event.get("ai_analysis", True),
        }

    result = validate_input(event)
    if not result.valid:
        raise ValueError(result.error)
    return {
        "valid": True,
        "params": {
            "period": result.params.period,
            "reference_date": result.params.reference_date,
            "ai_analysis": result.params.ai_analysis,
            "output_format": result.params.output_format,
        },
    }
