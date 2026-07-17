"""
Tests unitarios para el generador de reportes CSV.
"""
import csv
import io

import pytest

from src.generators.csv_generator import CSV_COLUMNS, generate_csv, _build_csv_row, _is_internal_user
from src.models import ProcessingResult, UserMetrics


def _make_user_metrics(
    user_id="u1",
    username="jdoe",
    display_name="John Doe",
    email="jdoe@example.com",
    credits_used=25.5,
    credits_monthly=100.0,
    credits_pct=10.0,
    conversations=5,
    total_messages=20,
    days_active=3,
    clients_used=None,
    chat_messages_sent=15,
    ai_code_lines=50,
    inline_suggestions=30,
    inline_accepted=20,
    prompt_count=10,
) -> UserMetrics:
    """Helper para crear instancias de UserMetrics para tests."""
    if clients_used is None:
        clients_used = ["vscode", "jetbrains"]
    return UserMetrics(
        user_id=user_id,
        username=username,
        display_name=display_name,
        email=email,
        credits_used=credits_used,
        credits_monthly=credits_monthly,
        credits_pct=credits_pct,
        conversations=conversations,
        total_messages=total_messages,
        days_active=days_active,
        clients_used=clients_used,
        chat_messages_sent=chat_messages_sent,
        ai_code_lines=ai_code_lines,
        inline_suggestions=inline_suggestions,
        inline_accepted=inline_accepted,
        prompt_count=prompt_count,
    )


class TestGenerateCsv:
    """Tests para la función generate_csv."""

    def test_genera_csv_con_encabezado_correcto(self):
        """Verifica que el CSV tiene exactamente las 16 columnas requeridas."""
        metrics = ProcessingResult(user_metrics=[_make_user_metrics()])
        result = generate_csv(metrics, "weekly", "2026-01-05", "2026-01-11")

        reader = csv.reader(io.StringIO(result))
        header = next(reader)

        assert header == CSV_COLUMNS
        assert len(header) == 16

    def test_genera_una_fila_por_usuario(self):
        """Verifica que se genera exactamente una fila por usuario procesado."""
        users = [
            _make_user_metrics(user_id="u1", username="user1"),
            _make_user_metrics(user_id="u2", username="user2"),
            _make_user_metrics(user_id="u3", username="user3"),
        ]
        metrics = ProcessingResult(user_metrics=users, total_users_processed=3)
        result = generate_csv(metrics, "daily", "2026-01-10", "2026-01-10")

        reader = csv.reader(io.StringIO(result))
        rows = list(reader)
        # 1 encabezado + 3 filas de datos
        assert len(rows) == 4

    def test_csv_vacio_sin_usuarios(self):
        """Verifica que sin usuarios solo se genera el encabezado."""
        metrics = ProcessingResult(user_metrics=[])
        result = generate_csv(metrics, "monthly", "2026-01-01", "2026-01-31")

        reader = csv.reader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 1  # Solo encabezado

    def test_valores_correctos_en_fila(self):
        """Verifica que los valores de cada columna son correctos."""
        user = _make_user_metrics(
            username="jsmith",
            display_name="Jane Smith",
            email="jsmith@example.com",
            credits_used=50.5,
            credits_monthly=200.0,
            credits_pct=20.0,
            conversations=10,
            total_messages=40,
            days_active=5,
            clients_used=["vscode", "jetbrains", "vim"],
            chat_messages_sent=30,
            ai_code_lines=100,
            inline_suggestions=60,
            inline_accepted=45,
            prompt_count=25,
        )
        metrics = ProcessingResult(user_metrics=[user])
        result = generate_csv(metrics, "weekly", "2026-01-05", "2026-01-11")

        reader = csv.DictReader(io.StringIO(result))
        row = next(reader)

        assert row["username"] == "jsmith"
        assert row["display_name"] == "Jane Smith"
        assert row["email"] == "jsmith@example.com"
        assert row["is_internal"] == "True"
        assert row["credits_used"] == "50.5"
        assert row["credits_monthly"] == "200.0"
        assert row["credits_pct"] == "20.0"
        assert row["conversations"] == "10"
        assert row["total_messages"] == "40"
        assert row["days_active"] == "5"
        assert row["clients_used"] == "3"  # Cantidad de clientes
        assert row["chat_messages_sent"] == "30"
        assert row["ai_code_lines"] == "100"
        assert row["inline_suggestions"] == "60"
        assert row["inline_accepted"] == "45"
        assert row["prompt_count"] == "25"

    def test_clients_used_es_conteo(self):
        """Verifica que clients_used exporta la cantidad de clientes como entero."""
        user = _make_user_metrics(clients_used=["vscode"])
        metrics = ProcessingResult(user_metrics=[user])
        result = generate_csv(metrics, "daily", "2026-01-10", "2026-01-10")

        reader = csv.DictReader(io.StringIO(result))
        row = next(reader)
        assert row["clients_used"] == "1"

    def test_clients_used_vacio(self):
        """Verifica que clients_used con lista vacía exporta 0."""
        user = _make_user_metrics(clients_used=[])
        metrics = ProcessingResult(user_metrics=[user])
        result = generate_csv(metrics, "daily", "2026-01-10", "2026-01-10")

        reader = csv.DictReader(io.StringIO(result))
        row = next(reader)
        assert row["clients_used"] == "0"

    def test_retorna_string(self):
        """Verifica que el resultado es un string."""
        metrics = ProcessingResult(user_metrics=[_make_user_metrics()])
        result = generate_csv(metrics, "weekly", "2026-01-05", "2026-01-11")
        assert isinstance(result, str)


class TestBuildCsvRow:
    """Tests para la función _build_csv_row."""

    def test_retorna_diccionario_con_16_claves(self):
        """Verifica que el diccionario tiene exactamente 16 claves."""
        user = _make_user_metrics()
        row = _build_csv_row(user)
        assert len(row) == 16
        assert set(row.keys()) == set(CSV_COLUMNS)


class TestIsInternalUser:
    """Tests para la función _is_internal_user."""

    def test_todos_los_usuarios_son_internos(self):
        """Todos los usuarios del roster son internos."""
        user = _make_user_metrics()
        assert _is_internal_user(user) is True
