"""Tests unitarios para src/utils/date_utils.py"""
from __future__ import annotations

from datetime import date

import pytest

from src.utils.date_utils import (
    calculate_schedule_params,
    date_prefixes,
    get_date_range,
)


class TestGetDateRange:
    """Tests para get_date_range."""

    def test_daily_returns_same_date(self):
        """Para periodo diario, start y end son la misma fecha."""
        ref = date(2026, 5, 15)
        start, end = get_date_range("daily", ref)
        assert start == ref
        assert end == ref

    def test_weekly_starts_on_monday(self):
        """Para periodo semanal, start es el lunes de la semana."""
        # 2026-05-15 es jueves
        ref = date(2026, 5, 15)
        start, end = get_date_range("weekly", ref)
        assert start == date(2026, 5, 11)  # lunes
        assert end == date(2026, 5, 17)    # domingo
        assert start.weekday() == 0  # lunes

    def test_weekly_when_ref_is_monday(self):
        """Si ref_date es lunes, la semana empieza ese mismo día."""
        ref = date(2026, 5, 11)  # lunes
        start, end = get_date_range("weekly", ref)
        assert start == date(2026, 5, 11)
        assert end == date(2026, 5, 17)

    def test_weekly_when_ref_is_sunday(self):
        """Si ref_date es domingo, la semana empieza el lunes anterior."""
        ref = date(2026, 5, 17)  # domingo
        start, end = get_date_range("weekly", ref)
        assert start == date(2026, 5, 11)
        assert end == date(2026, 5, 17)

    def test_monthly_full_month(self):
        """Para periodo mensual, cubre todo el mes."""
        ref = date(2026, 5, 15)
        start, end = get_date_range("monthly", ref)
        assert start == date(2026, 5, 1)
        assert end == date(2026, 5, 31)

    def test_monthly_february_non_leap(self):
        """Febrero en año no bisiesto tiene 28 días."""
        ref = date(2025, 2, 10)
        start, end = get_date_range("monthly", ref)
        assert start == date(2025, 2, 1)
        assert end == date(2025, 2, 28)

    def test_monthly_february_leap_year(self):
        """Febrero en año bisiesto tiene 29 días."""
        ref = date(2024, 2, 10)
        start, end = get_date_range("monthly", ref)
        assert start == date(2024, 2, 1)
        assert end == date(2024, 2, 29)

    def test_monthly_december(self):
        """Diciembre cruza al siguiente año correctamente."""
        ref = date(2026, 12, 15)
        start, end = get_date_range("monthly", ref)
        assert start == date(2026, 12, 1)
        assert end == date(2026, 12, 31)

    def test_invalid_period_raises_error(self):
        """Un periodo inválido lanza ValueError."""
        with pytest.raises(ValueError):
            get_date_range("yearly", date(2026, 5, 15))


class TestDatePrefixes:
    """Tests para date_prefixes."""

    def test_single_day(self):
        """Un solo día genera un prefijo."""
        result = date_prefixes(date(2026, 5, 15), date(2026, 5, 15))
        assert result == ["2026/05/15/"]

    def test_multiple_days(self):
        """Varios días generan prefijos consecutivos."""
        result = date_prefixes(date(2026, 5, 14), date(2026, 5, 16))
        assert result == ["2026/05/14/", "2026/05/15/", "2026/05/16/"]

    def test_cross_month_boundary(self):
        """Prefijos que cruzan límite de mes."""
        result = date_prefixes(date(2026, 4, 30), date(2026, 5, 2))
        assert result == ["2026/04/30/", "2026/05/01/", "2026/05/02/"]

    def test_empty_range(self):
        """Si start > end, retorna lista vacía."""
        result = date_prefixes(date(2026, 5, 16), date(2026, 5, 15))
        assert result == []


class TestCalculateScheduleParams:
    """Tests para calculate_schedule_params."""

    def test_daily_returns_yesterday(self):
        """Para daily, la fecha de referencia es ayer."""
        trigger = date(2026, 5, 15)
        params = calculate_schedule_params("daily", trigger)
        assert params.period == "daily"
        assert params.reference_date == "2026-05-14"

    def test_weekly_returns_current_monday(self):
        """Para weekly, la fecha de referencia es el lunes de la semana actual."""
        # 2026-06-19 es viernes (trigger del schedule semanal)
        trigger = date(2026, 6, 19)
        params = calculate_schedule_params("weekly", trigger)
        assert params.period == "weekly"
        assert params.reference_date == "2026-06-15"  # lunes de esta semana

    def test_weekly_from_non_friday(self):
        """Para weekly desde un día que no es viernes."""
        # 2026-05-15 es jueves
        trigger = date(2026, 5, 15)
        params = calculate_schedule_params("weekly", trigger)
        assert params.period == "weekly"
        assert params.reference_date == "2026-05-11"  # lunes de esa semana

    def test_monthly_returns_first_of_previous_month(self):
        """Para monthly, la fecha de referencia es el primer día del mes anterior."""
        trigger = date(2026, 5, 1)
        params = calculate_schedule_params("monthly", trigger)
        assert params.period == "monthly"
        assert params.reference_date == "2026-04-01"

    def test_monthly_january_goes_to_previous_year(self):
        """Para monthly en enero, retrocede al año anterior."""
        trigger = date(2026, 1, 1)
        params = calculate_schedule_params("monthly", trigger)
        assert params.period == "monthly"
        assert params.reference_date == "2025-12-01"

    def test_invalid_schedule_type_raises_error(self):
        """Un tipo de schedule inválido lanza ValueError."""
        with pytest.raises(ValueError):
            calculate_schedule_params("yearly", date(2026, 5, 15))
