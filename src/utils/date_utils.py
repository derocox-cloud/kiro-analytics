"""Utilidades de manejo de fechas para el pipeline de analytics."""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Tuple

from ..models import ScheduleParams


def get_date_range(period: str, ref_date: date) -> Tuple[date, date]:
    """
    Retorna el rango de fechas (start, end) según el periodo.

    Para "daily": start=ref_date, end=ref_date
    Para "weekly": start=lunes de la semana que contiene ref_date, end=domingo
    Para "monthly": start=primer día del mes, end=último día del mes
    """
    if period == "daily":
        return ref_date, ref_date
    elif period == "weekly":
        # Lunes de la semana que contiene ref_date
        start = ref_date - timedelta(days=ref_date.weekday())
        end = start + timedelta(days=6)
        return start, end
    elif period == "monthly":
        start = ref_date.replace(day=1)
        # Último día del mes: ir al siguiente mes y restar un día
        if start.month == 12:
            next_month_first = start.replace(year=start.year + 1, month=1, day=1)
        else:
            next_month_first = start.replace(month=start.month + 1, day=1)
        end = next_month_first - timedelta(days=1)
        return start, end
    else:
        raise ValueError(f"Periodo no válido: {period}. Debe ser 'daily', 'weekly' o 'monthly'.")


def date_prefixes(start: date, end: date) -> List[str]:
    """
    Genera lista de prefijos de fecha en formato 'YYYY/MM/DD/' para cada día en el rango.

    Usado para construir prefijos S3 al listar objetos.
    """
    prefixes = []
    current = start
    while current <= end:
        prefixes.append(f"{current.year}/{current.month:02d}/{current.day:02d}/")
        current += timedelta(days=1)
    return prefixes


def calculate_schedule_params(schedule_type: str, trigger_date: date) -> ScheduleParams:
    """
    Calcula los parámetros de ejecución para un schedule programado.

    Para daily: periodo="daily", reference_date = trigger_date - 1 día
    Para weekly: periodo="weekly", reference_date = lunes de la semana anterior
    Para monthly: periodo="monthly", reference_date = primer día del mes anterior
    """
    if schedule_type == "daily":
        reference = trigger_date - timedelta(days=1)
        return ScheduleParams(period="daily", reference_date=reference.isoformat())
    elif schedule_type == "weekly":
        # Lunes de la semana actual (el viernes reporta su propia semana lun-dom)
        current_monday = trigger_date - timedelta(days=trigger_date.weekday())
        return ScheduleParams(period="weekly", reference_date=current_monday.isoformat())
    elif schedule_type == "monthly":
        # Primer día del mes anterior
        first_of_current = trigger_date.replace(day=1)
        last_of_previous = first_of_current - timedelta(days=1)
        first_of_previous = last_of_previous.replace(day=1)
        return ScheduleParams(period="monthly", reference_date=first_of_previous.isoformat())
    else:
        raise ValueError(
            f"Tipo de schedule no válido: {schedule_type}. "
            "Debe ser 'daily', 'weekly' o 'monthly'."
        )
