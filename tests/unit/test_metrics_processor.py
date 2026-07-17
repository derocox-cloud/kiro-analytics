"""
Tests unitarios para el procesador de métricas por usuario.

Verifica la agregación de datos crudos, cálculo de créditos mensuales,
porcentaje de uso, y detección de usuarios inactivos.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.models import CollectionResult, CREDITS_PER_USER, User
from src.processors.metrics_processor import (
    _aggregate_analytics,
    _aggregate_prompts,
    _aggregate_user_reports,
    _calculate_monthly_credits,
    _get_enabled_users,
    process_metrics,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_roster():
    """Roster de ejemplo con usuarios habilitados y deshabilitados."""
    return [
        User(user_id="u1", username="alice", display_name="Alice A", email="alice@test.com", status="Enabled"),
        User(user_id="u2", username="bob", display_name="Bob B", email="bob@test.com", status="Enabled"),
        User(user_id="u3", username="carol", display_name="Carol C", email="carol@test.com", status="Disabled"),
        User(user_id="u4", username="dave", display_name="Dave D", email="dave@test.com", status="Enabled"),
    ]


@pytest.fixture
def sample_user_report_records():
    """Registros de user_report de ejemplo."""
    return [
        {
            "_normalized_user_id": "u1",
            "Credits_Used": "10.5",
            "Chat_Conversations": "3",
            "Total_Messages": "15",
            "Date": "2026-04-15",
            "Client_Type": "VSCode",
        },
        {
            "_normalized_user_id": "u1",
            "Credits_Used": "5.0",
            "Chat_Conversations": "2",
            "Total_Messages": "8",
            "Date": "2026-04-16",
            "Client_Type": "JetBrains",
        },
        {
            "_normalized_user_id": "u2",
            "Credits_Used": "20.0",
            "Chat_Conversations": "5",
            "Total_Messages": "30",
            "Date": "2026-04-15",
            "Client_Type": "VSCode",
        },
    ]


@pytest.fixture
def sample_analytics_records():
    """Registros de by_user_analytic de ejemplo."""
    return [
        {
            "_normalized_user_id": "u1",
            "Chat_MessagesSent": "10",
            "Chat_AICodeLines": "50",
            "Inline_SuggestionsCount": "20",
            "Inline_AcceptanceCount": "8",
        },
        {
            "_normalized_user_id": "u1",
            "Chat_MessagesSent": "5",
            "Chat_AICodeLines": "30",
            "Inline_SuggestionsCount": "10",
            "Inline_AcceptanceCount": "4",
        },
        {
            "_normalized_user_id": "u2",
            "Chat_MessagesSent": "15",
            "Chat_AICodeLines": "100",
            "Inline_SuggestionsCount": "50",
            "Inline_AcceptanceCount": "25",
        },
    ]


@pytest.fixture
def sample_prompt_records():
    """Registros de prompt-metadata de ejemplo."""
    return [
        {
            "_normalized_user_id": "u1",
            "generateAssistantResponseEventRequest": {
                "prompt": "Cómo crear una función en Python para leer archivos CSV",
                "timeStamp": "2026-04-15T10:00:00Z",
                "modelId": "claude-haiku",
                "chatTriggerType": "manual",
                "userId": "u1",
            },
        },
        {
            "_normalized_user_id": "u1",
            "generateAssistantResponseEventRequest": {
                "prompt": "Explica el patrón de diseño Observer",
                "timeStamp": "2026-04-15T11:00:00Z",
                "modelId": "claude-haiku",
                "chatTriggerType": "manual",
                "userId": "u1",
            },
        },
        {
            "_normalized_user_id": "u2",
            "generateAssistantResponseEventRequest": {
                "prompt": "Cómo configurar Docker para una app Node.js",
                "timeStamp": "2026-04-15T09:00:00Z",
                "modelId": "claude-haiku",
                "chatTriggerType": "manual",
                "userId": "u2",
            },
        },
    ]


# =============================================================================
# Tests para _get_enabled_users
# =============================================================================

class TestGetEnabledUsers:
    """Tests para la función _get_enabled_users."""

    def test_filtra_solo_habilitados(self, sample_roster):
        """Solo retorna usuarios con status Enabled."""
        result = _get_enabled_users(sample_roster)
        assert len(result) == 3
        assert "u1" in result
        assert "u2" in result
        assert "u4" in result
        assert "u3" not in result

    def test_roster_vacio(self):
        """Retorna diccionario vacío con roster vacío."""
        result = _get_enabled_users([])
        assert result == {}


# =============================================================================
# Tests para _aggregate_user_reports
# =============================================================================

class TestAggregateUserReports:
    """Tests para la función _aggregate_user_reports."""

    def test_suma_creditos_por_usuario(self, sample_user_report_records):
        """Suma correctamente los créditos por usuario."""
        result = _aggregate_user_reports(sample_user_report_records)
        assert result["u1"]["credits"] == pytest.approx(15.5)
        assert result["u2"]["credits"] == pytest.approx(20.0)

    def test_suma_conversaciones(self, sample_user_report_records):
        """Suma correctamente las conversaciones por usuario."""
        result = _aggregate_user_reports(sample_user_report_records)
        assert result["u1"]["conversations"] == 5
        assert result["u2"]["conversations"] == 5

    def test_suma_mensajes(self, sample_user_report_records):
        """Suma correctamente los mensajes por usuario."""
        result = _aggregate_user_reports(sample_user_report_records)
        assert result["u1"]["messages"] == 23
        assert result["u2"]["messages"] == 30

    def test_dias_activos_unicos(self, sample_user_report_records):
        """Cuenta días activos únicos por usuario."""
        result = _aggregate_user_reports(sample_user_report_records)
        assert result["u1"]["days_active"] == {"2026-04-15", "2026-04-16"}
        assert result["u2"]["days_active"] == {"2026-04-15"}

    def test_clientes_unicos(self, sample_user_report_records):
        """Recopila clientes únicos por usuario."""
        result = _aggregate_user_reports(sample_user_report_records)
        assert result["u1"]["clients"] == {"VSCode", "JetBrains"}
        assert result["u2"]["clients"] == {"VSCode"}

    def test_registros_vacios(self):
        """Retorna diccionario vacío con registros vacíos."""
        result = _aggregate_user_reports([])
        assert len(result) == 0

    def test_campos_nulos_o_vacios(self):
        """Maneja campos nulos o vacíos sin error."""
        records = [
            {
                "_normalized_user_id": "u1",
                "Credits_Used": "",
                "Chat_Conversations": None,
                "Total_Messages": "0",
                "Date": "",
                "Client_Type": "",
            }
        ]
        result = _aggregate_user_reports(records)
        assert result["u1"]["credits"] == 0.0
        assert result["u1"]["conversations"] == 0
        assert result["u1"]["messages"] == 0


# =============================================================================
# Tests para _aggregate_analytics
# =============================================================================

class TestAggregateAnalytics:
    """Tests para la función _aggregate_analytics."""

    def test_suma_metricas_por_usuario(self, sample_analytics_records):
        """Suma correctamente las métricas de analytics por usuario."""
        result = _aggregate_analytics(sample_analytics_records)
        assert result["u1"]["chat_messages_sent"] == 15
        assert result["u1"]["ai_code_lines"] == 80
        assert result["u1"]["inline_suggestions"] == 30
        assert result["u1"]["inline_accepted"] == 12

    def test_usuario_unico(self, sample_analytics_records):
        """Calcula correctamente para usuario con un solo registro."""
        result = _aggregate_analytics(sample_analytics_records)
        assert result["u2"]["chat_messages_sent"] == 15
        assert result["u2"]["ai_code_lines"] == 100
        assert result["u2"]["inline_suggestions"] == 50
        assert result["u2"]["inline_accepted"] == 25

    def test_registros_vacios(self):
        """Retorna diccionario vacío con registros vacíos."""
        result = _aggregate_analytics([])
        assert len(result) == 0


# =============================================================================
# Tests para _aggregate_prompts
# =============================================================================

class TestAggregatePrompts:
    """Tests para la función _aggregate_prompts."""

    def test_agrupa_prompts_por_usuario(self, sample_prompt_records):
        """Agrupa correctamente los prompts por usuario."""
        result = _aggregate_prompts(sample_prompt_records)
        assert len(result["u1"]) == 2
        assert len(result["u2"]) == 1

    def test_ignora_prompts_cortos(self):
        """Ignora prompts con menos de 5 caracteres."""
        records = [
            {
                "_normalized_user_id": "u1",
                "generateAssistantResponseEventRequest": {
                    "prompt": "hi",
                    "timeStamp": "",
                    "modelId": "",
                    "chatTriggerType": "",
                    "userId": "u1",
                },
            }
        ]
        result = _aggregate_prompts(records)
        assert len(result["u1"]) == 0

    def test_trunca_prompt_a_300_chars(self):
        """Trunca el texto del prompt a 300 caracteres."""
        long_prompt = "x" * 500
        records = [
            {
                "_normalized_user_id": "u1",
                "generateAssistantResponseEventRequest": {
                    "prompt": long_prompt,
                    "timeStamp": "",
                    "modelId": "",
                    "chatTriggerType": "",
                    "userId": "u1",
                },
            }
        ]
        result = _aggregate_prompts(records)
        assert len(result["u1"][0]["prompt"]) == 300


# =============================================================================
# Tests para _calculate_monthly_credits
# =============================================================================

class TestCalculateMonthlyCredits:
    """Tests para la función _calculate_monthly_credits."""

    def test_suma_creditos_del_mes(self):
        """Suma créditos desde día 1 del mes hasta end_date."""
        records = [
            {"_normalized_user_id": "u1", "Credits_Used": "10", "Date": "2026-04-01"},
            {"_normalized_user_id": "u1", "Credits_Used": "5", "Date": "2026-04-10"},
            {"_normalized_user_id": "u1", "Credits_Used": "3", "Date": "2026-04-15"},
            # Este registro está fuera del rango (mes anterior)
            {"_normalized_user_id": "u1", "Credits_Used": "100", "Date": "2026-03-31"},
        ]
        result = _calculate_monthly_credits(records, date(2026, 4, 15))
        assert result["u1"] == pytest.approx(18.0)

    def test_excluye_registros_posteriores_a_end_date(self):
        """Excluye registros con fecha posterior a end_date."""
        records = [
            {"_normalized_user_id": "u1", "Credits_Used": "10", "Date": "2026-04-15"},
            {"_normalized_user_id": "u1", "Credits_Used": "20", "Date": "2026-04-20"},
        ]
        result = _calculate_monthly_credits(records, date(2026, 4, 15))
        assert result["u1"] == pytest.approx(10.0)

    def test_multiples_usuarios(self):
        """Calcula créditos mensuales para múltiples usuarios."""
        records = [
            {"_normalized_user_id": "u1", "Credits_Used": "10", "Date": "2026-04-05"},
            {"_normalized_user_id": "u2", "Credits_Used": "25", "Date": "2026-04-05"},
        ]
        result = _calculate_monthly_credits(records, date(2026, 4, 10))
        assert result["u1"] == pytest.approx(10.0)
        assert result["u2"] == pytest.approx(25.0)

    def test_sin_registros(self):
        """Retorna diccionario vacío sin registros."""
        result = _calculate_monthly_credits([], date(2026, 4, 15))
        assert len(result) == 0


# =============================================================================
# Tests para process_metrics (integración del procesador)
# =============================================================================

class TestProcessMetrics:
    """Tests de integración para la función process_metrics."""

    def test_procesa_datos_completos(
        self, sample_roster, sample_user_report_records,
        sample_analytics_records, sample_prompt_records
    ):
        """Procesa correctamente datos de las tres fuentes."""
        raw_data = {
            "user_report": CollectionResult(
                source_type="user_report",
                records=sample_user_report_records,
            ),
            "by_user_analytic": CollectionResult(
                source_type="by_user_analytic",
                records=sample_analytics_records,
            ),
            "prompt-metadata": CollectionResult(
                source_type="prompt-metadata",
                records=sample_prompt_records,
            ),
        }

        result = process_metrics(
            raw_data=raw_data,
            roster=sample_roster,
            period="daily",
            start_date=date(2026, 4, 15),
            end_date=date(2026, 4, 16),
        )

        assert result.total_users_processed == 3  # u1, u2 activos + u4 inactivo (u3 disabled)
        assert len(result.user_metrics) == 3  # activos + inactivos habilitados
        assert len(result.inactive_users) == 1  # u4 sin actividad

    def test_creditos_pct_calculado_correctamente(self, sample_roster):
        """Verifica que credits_pct = credits_monthly / 1000 * 100."""
        records = [
            {
                "_normalized_user_id": "u1",
                "Credits_Used": "250",
                "Chat_Conversations": "0",
                "Total_Messages": "0",
                "Date": "2026-04-10",
                "Client_Type": "",
            }
        ]
        raw_data = {
            "user_report": CollectionResult(
                source_type="user_report", records=records
            ),
            "by_user_analytic": CollectionResult(
                source_type="by_user_analytic", records=[]
            ),
            "prompt-metadata": CollectionResult(
                source_type="prompt-metadata", records=[]
            ),
        }

        result = process_metrics(
            raw_data=raw_data,
            roster=sample_roster,
            period="daily",
            start_date=date(2026, 4, 10),
            end_date=date(2026, 4, 10),
        )

        u1_metrics = result.user_metrics[0]
        assert u1_metrics.credits_monthly == 250.0
        expected_pct = 250.0 / CREDITS_PER_USER * 100
        assert u1_metrics.credits_pct == pytest.approx(expected_pct, rel=0.01)

    def test_detecta_usuarios_inactivos(self, sample_roster):
        """Detecta usuarios Enabled sin registros en ninguna fuente."""
        # Solo u1 tiene actividad; u2 y u4 son inactivos
        records = [
            {
                "_normalized_user_id": "u1",
                "Credits_Used": "5",
                "Chat_Conversations": "1",
                "Total_Messages": "3",
                "Date": "2026-04-15",
                "Client_Type": "VSCode",
            }
        ]
        raw_data = {
            "user_report": CollectionResult(
                source_type="user_report", records=records
            ),
            "by_user_analytic": CollectionResult(
                source_type="by_user_analytic", records=[]
            ),
            "prompt-metadata": CollectionResult(
                source_type="prompt-metadata", records=[]
            ),
        }

        result = process_metrics(
            raw_data=raw_data,
            roster=sample_roster,
            period="daily",
            start_date=date(2026, 4, 15),
            end_date=date(2026, 4, 15),
        )

        inactive_ids = {u.user_id for u in result.inactive_users}
        assert "u2" in inactive_ids
        assert "u4" in inactive_ids
        assert "u1" not in inactive_ids
        assert "u3" not in inactive_ids  # u3 es Disabled, no se incluye

    def test_roster_vacio_retorna_resultado_vacio(self):
        """Con roster vacío retorna resultado sin métricas."""
        raw_data = {
            "user_report": CollectionResult(source_type="user_report", records=[]),
            "by_user_analytic": CollectionResult(source_type="by_user_analytic", records=[]),
            "prompt-metadata": CollectionResult(source_type="prompt-metadata", records=[]),
        }

        result = process_metrics(
            raw_data=raw_data,
            roster=[],
            period="daily",
            start_date=date(2026, 4, 15),
            end_date=date(2026, 4, 15),
        )

        assert result.total_users_processed == 0
        assert result.user_metrics == []
        assert result.inactive_users == []

    def test_fuentes_vacias_todos_inactivos(self, sample_roster):
        """Con fuentes vacías, todos los usuarios Enabled son inactivos."""
        raw_data = {
            "user_report": CollectionResult(source_type="user_report", records=[]),
            "by_user_analytic": CollectionResult(source_type="by_user_analytic", records=[]),
            "prompt-metadata": CollectionResult(source_type="prompt-metadata", records=[]),
        }

        result = process_metrics(
            raw_data=raw_data,
            roster=sample_roster,
            period="daily",
            start_date=date(2026, 4, 15),
            end_date=date(2026, 4, 15),
        )

        assert result.total_users_processed == 3  # u1, u2, u4 (Enabled, con métricas en 0)
        assert len(result.user_metrics) == 3
        assert len(result.inactive_users) == 3  # u1, u2, u4 (Enabled)

    def test_usuario_solo_en_analytics_es_activo(self, sample_roster):
        """Un usuario con registros solo en analytics no es inactivo."""
        analytics_records = [
            {
                "_normalized_user_id": "u2",
                "Chat_MessagesSent": "5",
                "Chat_AICodeLines": "20",
                "Inline_SuggestionsCount": "10",
                "Inline_AcceptanceCount": "3",
            }
        ]
        raw_data = {
            "user_report": CollectionResult(source_type="user_report", records=[]),
            "by_user_analytic": CollectionResult(
                source_type="by_user_analytic", records=analytics_records
            ),
            "prompt-metadata": CollectionResult(source_type="prompt-metadata", records=[]),
        }

        result = process_metrics(
            raw_data=raw_data,
            roster=sample_roster,
            period="daily",
            start_date=date(2026, 4, 15),
            end_date=date(2026, 4, 15),
        )

        active_ids = {m.user_id for m in result.user_metrics}
        inactive_ids = {u.user_id for u in result.inactive_users}
        assert "u2" in active_ids
        assert "u2" not in inactive_ids

    def test_usuario_solo_en_prompts_es_activo(self, sample_roster):
        """Un usuario con registros solo en prompts no es inactivo."""
        prompt_records = [
            {
                "_normalized_user_id": "u4",
                "generateAssistantResponseEventRequest": {
                    "prompt": "Cómo implementar un patrón singleton en Python",
                    "timeStamp": "2026-04-15T10:00:00Z",
                    "modelId": "claude-haiku",
                    "chatTriggerType": "manual",
                    "userId": "u4",
                },
            }
        ]
        raw_data = {
            "user_report": CollectionResult(source_type="user_report", records=[]),
            "by_user_analytic": CollectionResult(source_type="by_user_analytic", records=[]),
            "prompt-metadata": CollectionResult(
                source_type="prompt-metadata", records=prompt_records
            ),
        }

        result = process_metrics(
            raw_data=raw_data,
            roster=sample_roster,
            period="daily",
            start_date=date(2026, 4, 15),
            end_date=date(2026, 4, 15),
        )

        active_ids = {m.user_id for m in result.user_metrics}
        inactive_ids = {u.user_id for u in result.inactive_users}
        assert "u4" in active_ids
        assert "u4" not in inactive_ids

    def test_excluye_usuarios_disabled_de_metricas(self, sample_roster):
        """No genera métricas para usuarios con status diferente a Enabled."""
        records = [
            {
                "_normalized_user_id": "u3",  # Disabled
                "Credits_Used": "50",
                "Chat_Conversations": "10",
                "Total_Messages": "50",
                "Date": "2026-04-15",
                "Client_Type": "VSCode",
            }
        ]
        raw_data = {
            "user_report": CollectionResult(
                source_type="user_report", records=records
            ),
            "by_user_analytic": CollectionResult(source_type="by_user_analytic", records=[]),
            "prompt-metadata": CollectionResult(source_type="prompt-metadata", records=[]),
        }

        result = process_metrics(
            raw_data=raw_data,
            roster=sample_roster,
            period="daily",
            start_date=date(2026, 4, 15),
            end_date=date(2026, 4, 15),
        )

        metric_ids = {m.user_id for m in result.user_metrics}
        assert "u3" not in metric_ids

    def test_ordenado_por_creditos_descendente(self, sample_roster):
        """Las métricas se ordenan por créditos usados de mayor a menor."""
        records = [
            {"_normalized_user_id": "u1", "Credits_Used": "10", "Chat_Conversations": "0", "Total_Messages": "0", "Date": "2026-04-15", "Client_Type": ""},
            {"_normalized_user_id": "u2", "Credits_Used": "50", "Chat_Conversations": "0", "Total_Messages": "0", "Date": "2026-04-15", "Client_Type": ""},
            {"_normalized_user_id": "u4", "Credits_Used": "30", "Chat_Conversations": "0", "Total_Messages": "0", "Date": "2026-04-15", "Client_Type": ""},
        ]
        raw_data = {
            "user_report": CollectionResult(source_type="user_report", records=records),
            "by_user_analytic": CollectionResult(source_type="by_user_analytic", records=[]),
            "prompt-metadata": CollectionResult(source_type="prompt-metadata", records=[]),
        }

        result = process_metrics(
            raw_data=raw_data,
            roster=sample_roster,
            period="daily",
            start_date=date(2026, 4, 15),
            end_date=date(2026, 4, 15),
        )

        credits = [m.credits_used for m in result.user_metrics]
        assert credits == sorted(credits, reverse=True)
