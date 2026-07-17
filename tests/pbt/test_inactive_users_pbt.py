"""
Tests de propiedad (PBT) para la detección de usuarios inactivos.

Utiliza Hypothesis para verificar que el procesador de métricas detecta
correctamente a los usuarios inactivos según las propiedades de correctitud
definidas en el documento de diseño.

# Feature: aws-analytics-pipeline, Property 5: Detección de usuarios inactivos
# Validates: Requirements 3.5
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Set

from hypothesis import given, settings, strategies as st, assume

from src.models import CollectionResult, ProcessingResult, User
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
    min_size=2,
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
        max_size=8,
    ),
)

# Estrategia para status "Enabled"
enabled_status = st.just("Enabled")

# Estrategia para status no-Enabled (cualquier otro valor)
non_enabled_status = st.one_of(
    st.just("Disabled"),
    st.just("Suspended"),
    st.just("Pending"),
    st.just("Inactive"),
    st.just("enabled"),   # case-sensitive: no es "Enabled"
    st.just("ENABLED"),   # case-sensitive: no es "Enabled"
)

# Estrategia para generar un usuario habilitado
enabled_user_strategy = st.builds(
    User,
    user_id=user_id_strategy,
    username=username_strategy,
    display_name=display_name_strategy,
    email=email_strategy,
    status=enabled_status,
)

# Estrategia para generar un usuario no habilitado
disabled_user_strategy = st.builds(
    User,
    user_id=user_id_strategy,
    username=username_strategy,
    display_name=display_name_strategy,
    email=email_strategy,
    status=non_enabled_status,
)

# Estrategia para generar fechas válidas dentro de un rango razonable
date_strategy = st.dates(
    min_value=date(2024, 1, 1),
    max_value=date(2026, 12, 31),
)

# Estrategia para periodos válidos
period_strategy = st.sampled_from(["daily", "weekly", "monthly"])


def _build_user_report_record(user_id: str, ref_date: date) -> dict:
    """Construye un registro de user_report para un usuario dado."""
    return {
        "_normalized_user_id": user_id,
        "Credits_Used": "5.0",
        "Chat_Conversations": "2",
        "Total_Messages": "10",
        "Date": ref_date.isoformat(),
        "Client_Type": "vscode",
    }


def _build_analytics_record(user_id: str) -> dict:
    """Construye un registro de by_user_analytic para un usuario dado."""
    return {
        "_normalized_user_id": user_id,
        "Chat_MessagesSent": "5",
        "Chat_AICodeLines": "20",
        "Inline_SuggestionsCount": "10",
        "Inline_AcceptanceCount": "3",
    }


def _build_prompt_record(user_id: str) -> dict:
    """Construye un registro de prompt-metadata para un usuario dado."""
    return {
        "_normalized_user_id": user_id,
        "generateAssistantResponseEventRequest": {
            "prompt": "Escribe una función para ordenar una lista de números",
            "timeStamp": "2025-01-15T10:00:00Z",
            "modelId": "claude-haiku",
            "chatTriggerType": "manual",
        },
    }


def _build_raw_data(
    user_report_records: List[dict],
    analytics_records: List[dict],
    prompt_records: List[dict],
) -> Dict[str, CollectionResult]:
    """Construye el diccionario raw_data con CollectionResult por fuente."""
    return {
        "user_report": CollectionResult(
            source_type="user_report",
            records=user_report_records,
            file_count=len(user_report_records),
        ),
        "by_user_analytic": CollectionResult(
            source_type="by_user_analytic",
            records=analytics_records,
            file_count=len(analytics_records),
        ),
        "prompt-metadata": CollectionResult(
            source_type="prompt-metadata",
            records=prompt_records,
            file_count=len(prompt_records),
        ),
    }


# =============================================================================
# Tests de propiedad
# =============================================================================

class TestProperty5DeteccionUsuariosInactivos:
    """
    Property 5: Detección de usuarios inactivos.

    For any roster of Enabled users and any set of activity records, a user
    SHALL appear in the inactive list if and only if they are in the roster
    with status "Enabled" AND have zero records across all three data sources
    for the given period.

    # Feature: aws-analytics-pipeline, Property 5: Detección de usuarios inactivos
    **Validates: Requirements 3.5**
    """

    @given(
        enabled_users_inactive=st.lists(enabled_user_strategy, min_size=1, max_size=5),
        enabled_users_active=st.lists(enabled_user_strategy, min_size=1, max_size=5),
        disabled_users=st.lists(disabled_user_strategy, min_size=0, max_size=5),
        period=period_strategy,
        ref_date=date_strategy,
    )
    @settings(max_examples=150)
    def test_usuarios_enabled_sin_registros_aparecen_en_lista_inactivos(
        self,
        enabled_users_inactive: List[User],
        enabled_users_active: List[User],
        disabled_users: List[User],
        period: str,
        ref_date: date,
    ):
        """
        Verifica que todo usuario Enabled sin registros en ninguna de las tres
        fuentes aparece en la lista de usuarios inactivos.

        **Validates: Requirements 3.5**
        """
        # Asegurar que todos los user_ids son únicos entre los grupos
        inactive_ids = {u.user_id for u in enabled_users_inactive}
        active_ids = {u.user_id for u in enabled_users_active}
        disabled_ids = {u.user_id for u in disabled_users}
        assume(inactive_ids.isdisjoint(active_ids))
        assume(inactive_ids.isdisjoint(disabled_ids))
        assume(active_ids.isdisjoint(disabled_ids))

        # Construir registros solo para usuarios activos (en al menos una fuente)
        user_report_records = [
            _build_user_report_record(u.user_id, ref_date)
            for u in enabled_users_active
        ]
        analytics_records = [
            _build_analytics_record(u.user_id)
            for u in enabled_users_active
        ]
        prompt_records = [
            _build_prompt_record(u.user_id)
            for u in enabled_users_active
        ]

        # No hay registros para los usuarios inactivos ni para los disabled
        raw_data = _build_raw_data(user_report_records, analytics_records, prompt_records)
        roster = enabled_users_inactive + enabled_users_active + disabled_users

        start_date = ref_date.replace(day=1)
        result = process_metrics(raw_data, roster, period, start_date, ref_date)

        # Todos los usuarios Enabled sin registros deben estar en inactive_users
        inactive_user_ids = {u.user_id for u in result.inactive_users}
        for uid in inactive_ids:
            assert uid in inactive_user_ids, (
                f"Usuario Enabled '{uid}' sin registros debería estar en la lista "
                f"de inactivos pero no se encontró. Inactivos: {inactive_user_ids}"
            )

    @given(
        enabled_users_active=st.lists(enabled_user_strategy, min_size=1, max_size=5),
        disabled_users=st.lists(disabled_user_strategy, min_size=0, max_size=5),
        period=period_strategy,
        ref_date=date_strategy,
        source_index=st.integers(min_value=0, max_value=2),
    )
    @settings(max_examples=150)
    def test_usuarios_con_al_menos_un_registro_no_aparecen_en_inactivos(
        self,
        enabled_users_active: List[User],
        disabled_users: List[User],
        period: str,
        ref_date: date,
        source_index: int,
    ):
        """
        Verifica que ningún usuario con al menos un registro en cualquier fuente
        aparece en la lista de usuarios inactivos.

        **Validates: Requirements 3.5**
        """
        # Asegurar IDs únicos
        active_ids = {u.user_id for u in enabled_users_active}
        disabled_ids = {u.user_id for u in disabled_users}
        assume(active_ids.isdisjoint(disabled_ids))

        # Crear registros en al menos una fuente para cada usuario activo
        # source_index determina en cuál fuente se crea el registro
        user_report_records = []
        analytics_records = []
        prompt_records = []

        for user in enabled_users_active:
            if source_index == 0:
                user_report_records.append(
                    _build_user_report_record(user.user_id, ref_date)
                )
            elif source_index == 1:
                analytics_records.append(
                    _build_analytics_record(user.user_id)
                )
            else:
                prompt_records.append(
                    _build_prompt_record(user.user_id)
                )

        raw_data = _build_raw_data(user_report_records, analytics_records, prompt_records)
        roster = enabled_users_active + disabled_users

        start_date = ref_date.replace(day=1)
        result = process_metrics(raw_data, roster, period, start_date, ref_date)

        # Ningún usuario con registros debe estar en la lista de inactivos
        inactive_user_ids = {u.user_id for u in result.inactive_users}
        for uid in active_ids:
            assert uid not in inactive_user_ids, (
                f"Usuario Enabled '{uid}' con registros en fuente {source_index} "
                f"NO debería estar en la lista de inactivos. "
                f"Inactivos: {inactive_user_ids}"
            )

    @given(
        disabled_users=st.lists(disabled_user_strategy, min_size=1, max_size=8),
        enabled_users_active=st.lists(enabled_user_strategy, min_size=0, max_size=3),
        period=period_strategy,
        ref_date=date_strategy,
    )
    @settings(max_examples=150)
    def test_usuarios_no_enabled_nunca_aparecen_en_inactivos(
        self,
        disabled_users: List[User],
        enabled_users_active: List[User],
        period: str,
        ref_date: date,
    ):
        """
        Verifica que los usuarios con status distinto de "Enabled" nunca
        aparecen en la lista de usuarios inactivos, independientemente de
        si tienen actividad o no.

        **Validates: Requirements 3.5**
        """
        # Asegurar IDs únicos
        disabled_ids = {u.user_id for u in disabled_users}
        active_ids = {u.user_id for u in enabled_users_active}
        assume(disabled_ids.isdisjoint(active_ids))

        # Crear registros solo para usuarios activos habilitados
        user_report_records = [
            _build_user_report_record(u.user_id, ref_date)
            for u in enabled_users_active
        ]
        analytics_records = []
        prompt_records = []

        raw_data = _build_raw_data(user_report_records, analytics_records, prompt_records)
        roster = disabled_users + enabled_users_active

        start_date = ref_date.replace(day=1)
        result = process_metrics(raw_data, roster, period, start_date, ref_date)

        # Ningún usuario no-Enabled debe estar en la lista de inactivos
        inactive_user_ids = {u.user_id for u in result.inactive_users}
        for uid in disabled_ids:
            assert uid not in inactive_user_ids, (
                f"Usuario no-Enabled '{uid}' (status != 'Enabled') NO debería "
                f"estar en la lista de inactivos. Inactivos: {inactive_user_ids}"
            )

    @given(
        enabled_users_inactive=st.lists(enabled_user_strategy, min_size=1, max_size=5),
        enabled_users_active=st.lists(enabled_user_strategy, min_size=1, max_size=5),
        disabled_users=st.lists(disabled_user_strategy, min_size=0, max_size=3),
        period=period_strategy,
        ref_date=date_strategy,
    )
    @settings(max_examples=150)
    def test_inactivos_mas_activos_cubre_todos_los_usuarios_enabled(
        self,
        enabled_users_inactive: List[User],
        enabled_users_active: List[User],
        disabled_users: List[User],
        period: str,
        ref_date: date,
    ):
        """
        Verifica que la unión de la lista de inactivos y la lista de métricas
        activas cubre exactamente todos los usuarios Enabled del roster.
        No debe haber usuarios Enabled que no estén en ninguna de las dos listas.

        **Validates: Requirements 3.5**
        """
        # Asegurar IDs únicos entre grupos
        inactive_ids = {u.user_id for u in enabled_users_inactive}
        active_ids = {u.user_id for u in enabled_users_active}
        disabled_ids = {u.user_id for u in disabled_users}
        assume(inactive_ids.isdisjoint(active_ids))
        assume(inactive_ids.isdisjoint(disabled_ids))
        assume(active_ids.isdisjoint(disabled_ids))

        # Crear registros solo para usuarios activos
        user_report_records = [
            _build_user_report_record(u.user_id, ref_date)
            for u in enabled_users_active
        ]
        analytics_records = [
            _build_analytics_record(u.user_id)
            for u in enabled_users_active
        ]
        prompt_records = []

        raw_data = _build_raw_data(user_report_records, analytics_records, prompt_records)
        roster = enabled_users_inactive + enabled_users_active + disabled_users

        start_date = ref_date.replace(day=1)
        result = process_metrics(raw_data, roster, period, start_date, ref_date)

        # Obtener IDs de usuarios en métricas activas e inactivos
        active_metrics_ids = {m.user_id for m in result.user_metrics}
        inactive_result_ids = {u.user_id for u in result.inactive_users}

        # La unión debe cubrir todos los usuarios Enabled
        all_enabled_ids = inactive_ids | active_ids
        covered_ids = active_metrics_ids | inactive_result_ids

        assert all_enabled_ids == covered_ids, (
            f"La unión de activos + inactivos debe cubrir todos los Enabled. "
            f"Enabled esperados: {all_enabled_ids}, "
            f"Cubiertos: {covered_ids}, "
            f"Faltantes: {all_enabled_ids - covered_ids}, "
            f"Sobrantes: {covered_ids - all_enabled_ids}"
        )

        # No debe haber intersección entre activos e inactivos
        overlap = active_metrics_ids & inactive_result_ids
        assert len(overlap) == 0, (
            f"No debe haber usuarios en ambas listas (activos e inactivos). "
            f"Usuarios en ambas: {overlap}"
        )
