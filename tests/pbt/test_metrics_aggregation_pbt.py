"""
Tests de propiedad (PBT) para la agregación de métricas por usuario.

Utiliza Hypothesis para verificar que el procesador de métricas calcula
correctamente las métricas agregadas por usuario a partir de datos crudos
de las tres fuentes (user_report, by_user_analytic, prompt-metadata).

# Feature: aws-analytics-pipeline, Property 3: Agregación de métricas por usuario
# Validates: Requirements 3.1, 3.2
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List

from hypothesis import given, settings, strategies as st, assume

from src.models import CollectionResult, User
from src.processors.metrics_processor import process_metrics


# =============================================================================
# Estrategias (Generators)
# =============================================================================

# Estrategia para generar user_ids únicos (UUIDs simplificados)
user_id_strategy = st.text(
    alphabet=st.sampled_from("abcdef0123456789"),
    min_size=8,
    max_size=16,
).filter(lambda s: len(s) >= 8)

# Estrategia para generar usernames
username_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_"),
    min_size=3,
    max_size=15,
)

# Estrategia para generar display names
display_name_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz ÁÉÍÓÚ"),
    min_size=3,
    max_size=30,
).filter(lambda s: s.strip() != "")

# Estrategia para generar emails
email_strategy = st.builds(
    lambda user, domain: f"{user}@{domain}.com",
    user=st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
        min_size=3,
        max_size=10,
    ),
    domain=st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
        min_size=3,
        max_size=10,
    ),
)

# Estrategia para generar un usuario habilitado
enabled_user_strategy = st.builds(
    User,
    user_id=user_id_strategy,
    username=username_strategy,
    display_name=display_name_strategy,
    email=email_strategy,
    status=st.just("Enabled"),
)

# Estrategia para generar fechas dentro de un mes (para user_report)
def date_in_month_strategy(end_date: date):
    """Genera fechas entre el día 1 del mes de end_date y end_date."""
    month_start = end_date.replace(day=1)
    days_range = (end_date - month_start).days + 1
    return st.integers(min_value=0, max_value=days_range - 1).map(
        lambda d: (month_start + timedelta(days=d)).isoformat()
    )


# Estrategia para valores numéricos positivos (créditos)
credits_strategy = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)

# Estrategia para valores enteros positivos (conteos)
count_strategy = st.integers(min_value=0, max_value=50)


def user_report_record_strategy(user_id: str, date_str: str):
    """Genera un registro de user_report para un usuario y fecha dados."""
    return st.fixed_dictionaries({
        "_normalized_user_id": st.just(user_id),
        "Credits_Used": credits_strategy.map(lambda x: str(round(x, 2))),
        "Chat_Conversations": count_strategy.map(str),
        "Total_Messages": count_strategy.map(str),
        "Date": st.just(date_str),
        "Client_Type": st.sampled_from(["VSCode", "JetBrains", "Web", ""]),
    })


def analytics_record_strategy(user_id: str):
    """Genera un registro de by_user_analytic para un usuario dado."""
    return st.fixed_dictionaries({
        "_normalized_user_id": st.just(user_id),
        "Chat_MessagesSent": count_strategy.map(str),
        "Chat_AICodeLines": count_strategy.map(str),
        "Inline_SuggestionsCount": count_strategy.map(str),
        "Inline_AcceptanceCount": count_strategy.map(str),
    })


# =============================================================================
# Funciones auxiliares para calcular valores esperados
# =============================================================================

def _expected_credits_used(records: List[dict], user_id: str) -> float:
    """Calcula la suma esperada de Credits_Used para un usuario."""
    total = 0.0
    for r in records:
        if r.get("_normalized_user_id") == user_id:
            total += float(r.get("Credits_Used", 0) or 0)
    return round(total, 2)


def _expected_conversations(records: List[dict], user_id: str) -> int:
    """Calcula la suma esperada de Chat_Conversations para un usuario."""
    total = 0
    for r in records:
        if r.get("_normalized_user_id") == user_id:
            total += int(r.get("Chat_Conversations", 0) or 0)
    return total


def _expected_total_messages(records: List[dict], user_id: str) -> int:
    """Calcula la suma esperada de Total_Messages para un usuario."""
    total = 0
    for r in records:
        if r.get("_normalized_user_id") == user_id:
            total += int(r.get("Total_Messages", 0) or 0)
    return total


def _expected_days_active(records: List[dict], user_id: str) -> int:
    """Calcula el conteo esperado de fechas únicas para un usuario."""
    dates = set()
    for r in records:
        if r.get("_normalized_user_id") == user_id:
            d = r.get("Date", "")
            if d:
                dates.add(d)
    return len(dates)


def _expected_ai_code_lines(records: List[dict], user_id: str) -> int:
    """Calcula la suma esperada de Chat_AICodeLines para un usuario."""
    total = 0
    for r in records:
        if r.get("_normalized_user_id") == user_id:
            total += int(r.get("Chat_AICodeLines", 0) or 0)
    return total


def _expected_inline_suggestions(records: List[dict], user_id: str) -> int:
    """Calcula la suma esperada de Inline_SuggestionsCount para un usuario."""
    total = 0
    for r in records:
        if r.get("_normalized_user_id") == user_id:
            total += int(r.get("Inline_SuggestionsCount", 0) or 0)
    return total


def _expected_inline_accepted(records: List[dict], user_id: str) -> int:
    """Calcula la suma esperada de Inline_AcceptanceCount para un usuario."""
    total = 0
    for r in records:
        if r.get("_normalized_user_id") == user_id:
            total += int(r.get("Inline_AcceptanceCount", 0) or 0)
    return total


def _expected_credits_monthly(
    records: List[dict], user_id: str, end_date: date
) -> float:
    """Calcula créditos acumulados desde día 1 del mes hasta end_date."""
    month_start_str = end_date.replace(day=1).isoformat()
    end_date_str = end_date.isoformat()
    total = 0.0
    for r in records:
        if r.get("_normalized_user_id") == user_id:
            row_date = r.get("Date", "")
            if row_date and month_start_str <= row_date <= end_date_str:
                total += float(r.get("Credits_Used", 0) or 0)
    return round(total, 2)


# =============================================================================
# Tests de propiedad
# =============================================================================

class TestProperty3AgregacionMetricasPorUsuario:
    """
    Property 3: Agregación de métricas por usuario.

    For any set of raw data records across the three sources (user_report,
    analytics, prompts), the processor SHALL produce per-user aggregated metrics
    where each numeric field equals the sum of the corresponding values from all
    raw records for that user.

    # Feature: aws-analytics-pipeline, Property 3: Agregación de métricas por usuario
    **Validates: Requirements 3.1, 3.2**
    """

    @given(data=st.data())
    @settings(max_examples=100)
    def test_credits_used_es_suma_de_credits_used_por_usuario(self, data):
        """
        Verifica que credits_used agregado es igual a la suma de Credits_Used
        de todos los registros user_report para ese usuario.

        **Validates: Requirements 3.1, 3.2**
        """
        # Generar usuarios con IDs únicos
        num_users = data.draw(st.integers(min_value=1, max_value=3))
        users = []
        used_ids = set()
        for _ in range(num_users):
            user = data.draw(enabled_user_strategy)
            assume(user.user_id not in used_ids)
            used_ids.add(user.user_id)
            users.append(user)

        # Fecha de referencia fija para el test
        end_date = date(2025, 6, 15)
        start_date = end_date.replace(day=1)

        # Generar registros user_report para cada usuario
        user_report_records = []
        for user in users:
            num_records = data.draw(st.integers(min_value=1, max_value=5))
            for _ in range(num_records):
                date_str = data.draw(date_in_month_strategy(end_date))
                record = data.draw(user_report_record_strategy(user.user_id, date_str))
                user_report_records.append(record)

        # Construir raw_data con CollectionResult
        raw_data: Dict[str, CollectionResult] = {
            "user_report": CollectionResult(
                source_type="user_report",
                records=user_report_records,
            ),
            "by_user_analytic": CollectionResult(
                source_type="by_user_analytic",
                records=[],
            ),
            "prompt-metadata": CollectionResult(
                source_type="prompt-metadata",
                records=[],
            ),
        }

        # Ejecutar procesador
        result = process_metrics(raw_data, users, "daily", start_date, end_date)

        # Verificar credits_used para cada usuario
        metrics_by_user = {m.user_id: m for m in result.user_metrics}
        for user in users:
            expected = _expected_credits_used(user_report_records, user.user_id)
            actual = metrics_by_user[user.user_id].credits_used
            assert actual == expected, (
                f"credits_used para usuario '{user.user_id}': "
                f"esperado={expected}, obtenido={actual}"
            )

    @given(data=st.data())
    @settings(max_examples=100)
    def test_conversations_es_suma_de_chat_conversations_por_usuario(self, data):
        """
        Verifica que conversations agregado es igual a la suma de
        Chat_Conversations de todos los registros user_report para ese usuario.

        **Validates: Requirements 3.1, 3.2**
        """
        # Generar usuarios con IDs únicos
        num_users = data.draw(st.integers(min_value=1, max_value=3))
        users = []
        used_ids = set()
        for _ in range(num_users):
            user = data.draw(enabled_user_strategy)
            assume(user.user_id not in used_ids)
            used_ids.add(user.user_id)
            users.append(user)

        end_date = date(2025, 6, 15)
        start_date = end_date.replace(day=1)

        # Generar registros user_report
        user_report_records = []
        for user in users:
            num_records = data.draw(st.integers(min_value=1, max_value=5))
            for _ in range(num_records):
                date_str = data.draw(date_in_month_strategy(end_date))
                record = data.draw(user_report_record_strategy(user.user_id, date_str))
                user_report_records.append(record)

        raw_data: Dict[str, CollectionResult] = {
            "user_report": CollectionResult(
                source_type="user_report", records=user_report_records
            ),
            "by_user_analytic": CollectionResult(
                source_type="by_user_analytic", records=[]
            ),
            "prompt-metadata": CollectionResult(
                source_type="prompt-metadata", records=[]
            ),
        }

        result = process_metrics(raw_data, users, "daily", start_date, end_date)

        metrics_by_user = {m.user_id: m for m in result.user_metrics}
        for user in users:
            expected = _expected_conversations(user_report_records, user.user_id)
            actual = metrics_by_user[user.user_id].conversations
            assert actual == expected, (
                f"conversations para usuario '{user.user_id}': "
                f"esperado={expected}, obtenido={actual}"
            )

    @given(data=st.data())
    @settings(max_examples=100)
    def test_total_messages_es_suma_de_total_messages_por_usuario(self, data):
        """
        Verifica que total_messages agregado es igual a la suma de
        Total_Messages de todos los registros user_report para ese usuario.

        **Validates: Requirements 3.1, 3.2**
        """
        num_users = data.draw(st.integers(min_value=1, max_value=3))
        users = []
        used_ids = set()
        for _ in range(num_users):
            user = data.draw(enabled_user_strategy)
            assume(user.user_id not in used_ids)
            used_ids.add(user.user_id)
            users.append(user)

        end_date = date(2025, 6, 15)
        start_date = end_date.replace(day=1)

        user_report_records = []
        for user in users:
            num_records = data.draw(st.integers(min_value=1, max_value=5))
            for _ in range(num_records):
                date_str = data.draw(date_in_month_strategy(end_date))
                record = data.draw(user_report_record_strategy(user.user_id, date_str))
                user_report_records.append(record)

        raw_data: Dict[str, CollectionResult] = {
            "user_report": CollectionResult(
                source_type="user_report", records=user_report_records
            ),
            "by_user_analytic": CollectionResult(
                source_type="by_user_analytic", records=[]
            ),
            "prompt-metadata": CollectionResult(
                source_type="prompt-metadata", records=[]
            ),
        }

        result = process_metrics(raw_data, users, "daily", start_date, end_date)

        metrics_by_user = {m.user_id: m for m in result.user_metrics}
        for user in users:
            expected = _expected_total_messages(user_report_records, user.user_id)
            actual = metrics_by_user[user.user_id].total_messages
            assert actual == expected, (
                f"total_messages para usuario '{user.user_id}': "
                f"esperado={expected}, obtenido={actual}"
            )

    @given(data=st.data())
    @settings(max_examples=100)
    def test_days_active_es_conteo_de_fechas_unicas_por_usuario(self, data):
        """
        Verifica que days_active es igual al conteo de valores únicos de Date
        en los registros user_report para ese usuario.

        **Validates: Requirements 3.1, 3.2**
        """
        num_users = data.draw(st.integers(min_value=1, max_value=3))
        users = []
        used_ids = set()
        for _ in range(num_users):
            user = data.draw(enabled_user_strategy)
            assume(user.user_id not in used_ids)
            used_ids.add(user.user_id)
            users.append(user)

        end_date = date(2025, 6, 15)
        start_date = end_date.replace(day=1)

        user_report_records = []
        for user in users:
            num_records = data.draw(st.integers(min_value=1, max_value=5))
            for _ in range(num_records):
                date_str = data.draw(date_in_month_strategy(end_date))
                record = data.draw(user_report_record_strategy(user.user_id, date_str))
                user_report_records.append(record)

        raw_data: Dict[str, CollectionResult] = {
            "user_report": CollectionResult(
                source_type="user_report", records=user_report_records
            ),
            "by_user_analytic": CollectionResult(
                source_type="by_user_analytic", records=[]
            ),
            "prompt-metadata": CollectionResult(
                source_type="prompt-metadata", records=[]
            ),
        }

        result = process_metrics(raw_data, users, "daily", start_date, end_date)

        metrics_by_user = {m.user_id: m for m in result.user_metrics}
        for user in users:
            expected = _expected_days_active(user_report_records, user.user_id)
            actual = metrics_by_user[user.user_id].days_active
            assert actual == expected, (
                f"days_active para usuario '{user.user_id}': "
                f"esperado={expected}, obtenido={actual}"
            )

    @given(data=st.data())
    @settings(max_examples=100)
    def test_ai_code_lines_es_suma_de_chat_aicodelines_por_usuario(self, data):
        """
        Verifica que ai_code_lines es igual a la suma de Chat_AICodeLines
        de todos los registros by_user_analytic para ese usuario.

        **Validates: Requirements 3.1, 3.2**
        """
        num_users = data.draw(st.integers(min_value=1, max_value=3))
        users = []
        used_ids = set()
        for _ in range(num_users):
            user = data.draw(enabled_user_strategy)
            assume(user.user_id not in used_ids)
            used_ids.add(user.user_id)
            users.append(user)

        end_date = date(2025, 6, 15)
        start_date = end_date.replace(day=1)

        # Generar registros analytics para cada usuario
        analytics_records = []
        for user in users:
            num_records = data.draw(st.integers(min_value=1, max_value=5))
            for _ in range(num_records):
                record = data.draw(analytics_record_strategy(user.user_id))
                analytics_records.append(record)

        raw_data: Dict[str, CollectionResult] = {
            "user_report": CollectionResult(
                source_type="user_report", records=[]
            ),
            "by_user_analytic": CollectionResult(
                source_type="by_user_analytic", records=analytics_records
            ),
            "prompt-metadata": CollectionResult(
                source_type="prompt-metadata", records=[]
            ),
        }

        result = process_metrics(raw_data, users, "daily", start_date, end_date)

        metrics_by_user = {m.user_id: m for m in result.user_metrics}
        for user in users:
            expected = _expected_ai_code_lines(analytics_records, user.user_id)
            actual = metrics_by_user[user.user_id].ai_code_lines
            assert actual == expected, (
                f"ai_code_lines para usuario '{user.user_id}': "
                f"esperado={expected}, obtenido={actual}"
            )

    @given(data=st.data())
    @settings(max_examples=100)
    def test_inline_suggestions_es_suma_de_suggestionscount_por_usuario(self, data):
        """
        Verifica que inline_suggestions es igual a la suma de
        Inline_SuggestionsCount de todos los registros by_user_analytic
        para ese usuario.

        **Validates: Requirements 3.1, 3.2**
        """
        num_users = data.draw(st.integers(min_value=1, max_value=3))
        users = []
        used_ids = set()
        for _ in range(num_users):
            user = data.draw(enabled_user_strategy)
            assume(user.user_id not in used_ids)
            used_ids.add(user.user_id)
            users.append(user)

        end_date = date(2025, 6, 15)
        start_date = end_date.replace(day=1)

        analytics_records = []
        for user in users:
            num_records = data.draw(st.integers(min_value=1, max_value=5))
            for _ in range(num_records):
                record = data.draw(analytics_record_strategy(user.user_id))
                analytics_records.append(record)

        raw_data: Dict[str, CollectionResult] = {
            "user_report": CollectionResult(
                source_type="user_report", records=[]
            ),
            "by_user_analytic": CollectionResult(
                source_type="by_user_analytic", records=analytics_records
            ),
            "prompt-metadata": CollectionResult(
                source_type="prompt-metadata", records=[]
            ),
        }

        result = process_metrics(raw_data, users, "daily", start_date, end_date)

        metrics_by_user = {m.user_id: m for m in result.user_metrics}
        for user in users:
            expected = _expected_inline_suggestions(analytics_records, user.user_id)
            actual = metrics_by_user[user.user_id].inline_suggestions
            assert actual == expected, (
                f"inline_suggestions para usuario '{user.user_id}': "
                f"esperado={expected}, obtenido={actual}"
            )

    @given(data=st.data())
    @settings(max_examples=100)
    def test_inline_accepted_es_suma_de_acceptancecount_por_usuario(self, data):
        """
        Verifica que inline_accepted es igual a la suma de
        Inline_AcceptanceCount de todos los registros by_user_analytic
        para ese usuario.

        **Validates: Requirements 3.1, 3.2**
        """
        num_users = data.draw(st.integers(min_value=1, max_value=3))
        users = []
        used_ids = set()
        for _ in range(num_users):
            user = data.draw(enabled_user_strategy)
            assume(user.user_id not in used_ids)
            used_ids.add(user.user_id)
            users.append(user)

        end_date = date(2025, 6, 15)
        start_date = end_date.replace(day=1)

        analytics_records = []
        for user in users:
            num_records = data.draw(st.integers(min_value=1, max_value=5))
            for _ in range(num_records):
                record = data.draw(analytics_record_strategy(user.user_id))
                analytics_records.append(record)

        raw_data: Dict[str, CollectionResult] = {
            "user_report": CollectionResult(
                source_type="user_report", records=[]
            ),
            "by_user_analytic": CollectionResult(
                source_type="by_user_analytic", records=analytics_records
            ),
            "prompt-metadata": CollectionResult(
                source_type="prompt-metadata", records=[]
            ),
        }

        result = process_metrics(raw_data, users, "daily", start_date, end_date)

        metrics_by_user = {m.user_id: m for m in result.user_metrics}
        for user in users:
            expected = _expected_inline_accepted(analytics_records, user.user_id)
            actual = metrics_by_user[user.user_id].inline_accepted
            assert actual == expected, (
                f"inline_accepted para usuario '{user.user_id}': "
                f"esperado={expected}, obtenido={actual}"
            )

    @given(data=st.data())
    @settings(max_examples=100)
    def test_credits_monthly_es_suma_creditos_desde_dia_1_hasta_end_date(self, data):
        """
        Verifica que credits_monthly es igual a la suma de créditos desde
        el día 1 del mes hasta end_date para ese usuario.

        **Validates: Requirements 3.1, 3.2**
        """
        num_users = data.draw(st.integers(min_value=1, max_value=3))
        users = []
        used_ids = set()
        for _ in range(num_users):
            user = data.draw(enabled_user_strategy)
            assume(user.user_id not in used_ids)
            used_ids.add(user.user_id)
            users.append(user)

        end_date = date(2025, 6, 15)
        start_date = end_date.replace(day=1)

        # Generar registros con fechas dentro y fuera del rango mensual
        user_report_records = []
        for user in users:
            # Registros dentro del mes (día 1 a end_date)
            num_in_month = data.draw(st.integers(min_value=1, max_value=4))
            for _ in range(num_in_month):
                date_str = data.draw(date_in_month_strategy(end_date))
                record = data.draw(user_report_record_strategy(user.user_id, date_str))
                user_report_records.append(record)

        raw_data: Dict[str, CollectionResult] = {
            "user_report": CollectionResult(
                source_type="user_report", records=user_report_records
            ),
            "by_user_analytic": CollectionResult(
                source_type="by_user_analytic", records=[]
            ),
            "prompt-metadata": CollectionResult(
                source_type="prompt-metadata", records=[]
            ),
        }

        result = process_metrics(raw_data, users, "daily", start_date, end_date)

        metrics_by_user = {m.user_id: m for m in result.user_metrics}
        for user in users:
            expected = _expected_credits_monthly(
                user_report_records, user.user_id, end_date
            )
            actual = metrics_by_user[user.user_id].credits_monthly
            assert actual == expected, (
                f"credits_monthly para usuario '{user.user_id}': "
                f"esperado={expected}, obtenido={actual}"
            )

    @given(data=st.data())
    @settings(max_examples=100)
    def test_credits_pct_es_credits_monthly_dividido_1000_por_100(self, data):
        """
        Verifica que credits_pct es igual a credits_monthly / 1000 * 100
        para cada usuario.

        **Validates: Requirements 3.1, 3.2**
        """
        num_users = data.draw(st.integers(min_value=1, max_value=3))
        users = []
        used_ids = set()
        for _ in range(num_users):
            user = data.draw(enabled_user_strategy)
            assume(user.user_id not in used_ids)
            used_ids.add(user.user_id)
            users.append(user)

        end_date = date(2025, 6, 15)
        start_date = end_date.replace(day=1)

        user_report_records = []
        for user in users:
            num_records = data.draw(st.integers(min_value=1, max_value=4))
            for _ in range(num_records):
                date_str = data.draw(date_in_month_strategy(end_date))
                record = data.draw(user_report_record_strategy(user.user_id, date_str))
                user_report_records.append(record)

        raw_data: Dict[str, CollectionResult] = {
            "user_report": CollectionResult(
                source_type="user_report", records=user_report_records
            ),
            "by_user_analytic": CollectionResult(
                source_type="by_user_analytic", records=[]
            ),
            "prompt-metadata": CollectionResult(
                source_type="prompt-metadata", records=[]
            ),
        }

        result = process_metrics(raw_data, users, "daily", start_date, end_date)

        metrics_by_user = {m.user_id: m for m in result.user_metrics}
        for user in users:
            credits_monthly = metrics_by_user[user.user_id].credits_monthly
            expected_pct = round(credits_monthly / 1000 * 100, 1)
            actual_pct = metrics_by_user[user.user_id].credits_pct
            assert actual_pct == expected_pct, (
                f"credits_pct para usuario '{user.user_id}': "
                f"esperado={expected_pct}, obtenido={actual_pct}. "
                f"credits_monthly={credits_monthly}"
            )
