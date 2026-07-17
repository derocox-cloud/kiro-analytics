"""Tests unitarios para src/validators/input_validator.py"""
from __future__ import annotations

import pytest

from src.validators.input_validator import validate_input


class TestValidateInputValid:
    """Tests para entradas válidas."""

    def test_entrada_minima_valida(self):
        """Acepta entrada con solo period y reference_date."""
        result = validate_input({
            "period": "daily",
            "reference_date": "2026-05-15",
        })
        assert result.valid is True
        assert result.params is not None
        assert result.params.period == "daily"
        assert result.params.reference_date == "2026-05-15"
        assert result.params.ai_analysis is True  # default
        assert result.params.output_format == "both"  # default

    def test_todos_los_periodos_validos(self):
        """Acepta daily, weekly y monthly."""
        for period in ("daily", "weekly", "monthly"):
            result = validate_input({
                "period": period,
                "reference_date": "2026-01-01",
            })
            assert result.valid is True
            assert result.params.period == period

    def test_ai_analysis_false(self):
        """Acepta ai_analysis=False."""
        result = validate_input({
            "period": "weekly",
            "reference_date": "2026-05-15",
            "ai_analysis": False,
        })
        assert result.valid is True
        assert result.params.ai_analysis is False

    def test_output_format_html(self):
        """Acepta output_format='html'."""
        result = validate_input({
            "period": "monthly",
            "reference_date": "2026-05-01",
            "output_format": "html",
        })
        assert result.valid is True
        assert result.params.output_format == "html"

    def test_output_format_csv(self):
        """Acepta output_format='csv'."""
        result = validate_input({
            "period": "daily",
            "reference_date": "2026-05-15",
            "output_format": "csv",
        })
        assert result.valid is True
        assert result.params.output_format == "csv"

    def test_fecha_bisiesto_valida(self):
        """Acepta 29 de febrero en año bisiesto."""
        result = validate_input({
            "period": "daily",
            "reference_date": "2024-02-29",
        })
        assert result.valid is True

    def test_entrada_completa(self):
        """Acepta entrada con todos los parámetros explícitos."""
        result = validate_input({
            "period": "weekly",
            "reference_date": "2026-05-11",
            "ai_analysis": True,
            "output_format": "both",
        })
        assert result.valid is True
        assert result.error is None


class TestValidateInputInvalid:
    """Tests para entradas inválidas."""

    def test_period_faltante(self):
        """Rechaza si falta period."""
        result = validate_input({"reference_date": "2026-05-15"})
        assert result.valid is False
        assert "period" in result.error
        assert result.params is None

    def test_period_invalido(self):
        """Rechaza period con valor no permitido."""
        result = validate_input({
            "period": "yearly",
            "reference_date": "2026-05-15",
        })
        assert result.valid is False
        assert "period" in result.error
        assert "yearly" in result.error

    def test_reference_date_faltante(self):
        """Rechaza si falta reference_date."""
        result = validate_input({"period": "daily"})
        assert result.valid is False
        assert "reference_date" in result.error

    def test_reference_date_formato_incorrecto(self):
        """Rechaza fecha con formato incorrecto."""
        result = validate_input({
            "period": "daily",
            "reference_date": "15-05-2026",
        })
        assert result.valid is False
        assert "reference_date" in result.error
        assert "YYYY-MM-DD" in result.error

    def test_reference_date_fecha_invalida(self):
        """Rechaza fecha calendario inválida (31 de febrero)."""
        result = validate_input({
            "period": "daily",
            "reference_date": "2026-02-30",
        })
        assert result.valid is False
        assert "reference_date" in result.error

    def test_reference_date_bisiesto_invalido(self):
        """Rechaza 29 de febrero en año no bisiesto."""
        result = validate_input({
            "period": "daily",
            "reference_date": "2025-02-29",
        })
        assert result.valid is False
        assert "reference_date" in result.error

    def test_ai_analysis_no_booleano(self):
        """Rechaza ai_analysis con valor no booleano."""
        result = validate_input({
            "period": "daily",
            "reference_date": "2026-05-15",
            "ai_analysis": "yes",
        })
        assert result.valid is False
        assert "ai_analysis" in result.error
        assert "booleano" in result.error

    def test_output_format_invalido(self):
        """Rechaza output_format con valor no permitido."""
        result = validate_input({
            "period": "daily",
            "reference_date": "2026-05-15",
            "output_format": "pdf",
        })
        assert result.valid is False
        assert "output_format" in result.error
        assert "pdf" in result.error

    def test_evento_no_diccionario(self):
        """Rechaza si el evento no es un diccionario."""
        result = validate_input("not a dict")
        assert result.valid is False
        assert "diccionario" in result.error

    def test_reference_date_no_string(self):
        """Rechaza reference_date que no sea string."""
        result = validate_input({
            "period": "daily",
            "reference_date": 20260515,
        })
        assert result.valid is False
        assert "reference_date" in result.error

    def test_reference_date_mes_invalido(self):
        """Rechaza fecha con mes 13."""
        result = validate_input({
            "period": "daily",
            "reference_date": "2026-13-01",
        })
        assert result.valid is False

    def test_reference_date_dia_invalido(self):
        """Rechaza fecha con día 32."""
        result = validate_input({
            "period": "daily",
            "reference_date": "2026-01-32",
        })
        assert result.valid is False
