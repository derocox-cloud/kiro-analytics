"""
Tests de propiedad (PBT) para el filtrado de usuarios por status Enabled.

Utiliza Hypothesis para verificar que las funciones de filtrado del recolector
cumplen con las propiedades de correctitud definidas en el documento de diseño.

# Feature: aws-analytics-pipeline, Property 2: Filtrado de usuarios por status Enabled
# Validates: Requirements 2.5, 10.5
"""
from __future__ import annotations

import csv
import io
from typing import List

from hypothesis import given, settings, strategies as st, assume

from src.collectors.collector import (
    _get_enabled_user_ids,
    _parse_csv_records,
    _parse_json_gz_records,
)
from src.models import User


# =============================================================================
# Estrategias (Generators)
# =============================================================================

# Estrategia para generar user_ids únicos (UUIDs simplificados)
user_id_strategy = st.text(
    alphabet=st.sampled_from("abcdef0123456789-"),
    min_size=8,
    max_size=36,
).filter(lambda s: len(s.strip("-")) > 0 and s.strip("-") == s)

# Estrategia para generar usernames
username_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_"),
    min_size=3,
    max_size=20,
)

# Estrategia para generar display names
display_name_strategy = st.text(min_size=1, max_size=50).filter(
    lambda s: s.strip() != ""
)

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

# Estrategia para status "Enabled" (el único válido para inclusión)
enabled_status = st.just("Enabled")

# Estrategia para status no-Enabled (cualquier otro valor)
non_enabled_status = st.one_of(
    st.just("Disabled"),
    st.just("Suspended"),
    st.just("Pending"),
    st.just("Inactive"),
    st.just("enabled"),  # case-sensitive: no es "Enabled"
    st.just("ENABLED"),  # case-sensitive: no es "Enabled"
    st.text(min_size=1, max_size=20).filter(lambda s: s != "Enabled"),
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


def _build_csv_content(user_ids: List[str]) -> str:
    """Construye contenido CSV con registros para los user_ids dados."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["UserId", "Credits", "Conversations", "Messages"])
    for uid in user_ids:
        writer.writerow([uid, "10.5", "3", "15"])
    return output.getvalue()


def _build_json_gz_data(user_ids: List[str]) -> dict:
    """Construye estructura JSON.gz con registros para los user_ids dados."""
    records = []
    for uid in user_ids:
        records.append({
            "generateAssistantResponseEventRequest": {
                "userId": uid,
                "conversationId": "conv-123",
            }
        })
    return {"records": records}


# =============================================================================
# Tests de propiedad
# =============================================================================

class TestProperty2FiltradoUsuariosPorStatus:
    """
    Property 2: Filtrado de usuarios por status Enabled.

    For any roster of users and any set of data records, the filtering function
    SHALL include only records belonging to users whose status field equals
    "Enabled", and the output SHALL never contain records for users with any
    other status value.

    # Feature: aws-analytics-pipeline, Property 2: Filtrado de usuarios por status Enabled
    # Validates: Requirements 2.5, 10.5
    """

    @given(
        enabled_users=st.lists(enabled_user_strategy, min_size=1, max_size=10),
        disabled_users=st.lists(disabled_user_strategy, min_size=0, max_size=10),
    )
    @settings(max_examples=150)
    def test_get_enabled_user_ids_solo_retorna_ids_de_usuarios_enabled(
        self, enabled_users: List[User], disabled_users: List[User]
    ):
        """
        _get_enabled_user_ids solo retorna IDs de usuarios con status "Enabled".
        Nunca incluye IDs de usuarios con otro status.

        **Validates: Requirements 2.5, 10.5**
        """
        # Asegurar que no hay user_ids duplicados entre enabled y disabled
        enabled_ids_set = {u.user_id for u in enabled_users}
        disabled_ids_set = {u.user_id for u in disabled_users}
        assume(enabled_ids_set.isdisjoint(disabled_ids_set))

        roster = enabled_users + disabled_users
        result = _get_enabled_user_ids(roster)

        # Solo IDs de usuarios Enabled deben estar en el resultado
        assert result == enabled_ids_set, (
            f"Resultado debe contener solo IDs de usuarios Enabled. "
            f"Esperado: {enabled_ids_set}, Obtenido: {result}"
        )

        # Ningún ID de usuario no-Enabled debe estar en el resultado
        for uid in disabled_ids_set:
            assert uid not in result, (
                f"ID de usuario no-Enabled '{uid}' no debe estar en el resultado"
            )

    @given(
        enabled_users=st.lists(enabled_user_strategy, min_size=1, max_size=8),
        disabled_users=st.lists(disabled_user_strategy, min_size=1, max_size=8),
    )
    @settings(max_examples=150)
    def test_parse_csv_records_solo_incluye_registros_de_usuarios_enabled(
        self, enabled_users: List[User], disabled_users: List[User]
    ):
        """
        _parse_csv_records solo incluye registros para usuarios habilitados.
        Registros de usuarios no-Enabled nunca aparecen en la salida.

        **Validates: Requirements 2.5, 10.5**
        """
        # Asegurar IDs únicos
        enabled_ids_set = {u.user_id for u in enabled_users}
        disabled_ids_set = {u.user_id for u in disabled_users}
        assume(enabled_ids_set.isdisjoint(disabled_ids_set))

        # Construir CSV con registros de ambos tipos de usuarios
        all_user_ids = list(enabled_ids_set) + list(disabled_ids_set)
        csv_content = _build_csv_content(all_user_ids)

        # Parsear con solo los IDs habilitados
        records = _parse_csv_records(csv_content, enabled_ids_set)

        # Todos los registros retornados deben pertenecer a usuarios Enabled
        for record in records:
            normalized_uid = record.get("_normalized_user_id", "")
            assert normalized_uid in enabled_ids_set, (
                f"Registro con user_id '{normalized_uid}' no pertenece a un "
                f"usuario Enabled. IDs habilitados: {enabled_ids_set}"
            )

        # Ningún registro debe pertenecer a usuarios no-Enabled
        for record in records:
            normalized_uid = record.get("_normalized_user_id", "")
            assert normalized_uid not in disabled_ids_set, (
                f"Registro con user_id '{normalized_uid}' pertenece a un "
                f"usuario no-Enabled y no debería estar en la salida"
            )

    @given(
        enabled_users=st.lists(enabled_user_strategy, min_size=1, max_size=8),
        disabled_users=st.lists(disabled_user_strategy, min_size=1, max_size=8),
    )
    @settings(max_examples=150)
    def test_parse_json_gz_records_solo_incluye_registros_de_usuarios_enabled(
        self, enabled_users: List[User], disabled_users: List[User]
    ):
        """
        _parse_json_gz_records solo incluye registros para usuarios habilitados.
        Registros de usuarios no-Enabled nunca aparecen en la salida.

        **Validates: Requirements 2.5, 10.5**
        """
        # Asegurar IDs únicos
        enabled_ids_set = {u.user_id for u in enabled_users}
        disabled_ids_set = {u.user_id for u in disabled_users}
        assume(enabled_ids_set.isdisjoint(disabled_ids_set))

        # Construir datos JSON con registros de ambos tipos de usuarios
        all_user_ids = list(enabled_ids_set) + list(disabled_ids_set)
        json_data = _build_json_gz_data(all_user_ids)

        # Parsear con solo los IDs habilitados
        records = _parse_json_gz_records(json_data, enabled_ids_set)

        # Todos los registros retornados deben pertenecer a usuarios Enabled
        for record in records:
            normalized_uid = record.get("_normalized_user_id", "")
            assert normalized_uid in enabled_ids_set, (
                f"Registro JSON con user_id '{normalized_uid}' no pertenece a un "
                f"usuario Enabled. IDs habilitados: {enabled_ids_set}"
            )

        # Ningún registro debe pertenecer a usuarios no-Enabled
        for record in records:
            normalized_uid = record.get("_normalized_user_id", "")
            assert normalized_uid not in disabled_ids_set, (
                f"Registro JSON con user_id '{normalized_uid}' pertenece a un "
                f"usuario no-Enabled y no debería estar en la salida"
            )

    @given(
        enabled_users=st.lists(enabled_user_strategy, min_size=1, max_size=8),
        disabled_users=st.lists(disabled_user_strategy, min_size=0, max_size=8),
    )
    @settings(max_examples=150)
    def test_todos_los_registros_de_usuarios_enabled_se_incluyen_en_csv(
        self, enabled_users: List[User], disabled_users: List[User]
    ):
        """
        Todos los registros que pertenecen a usuarios Enabled y existen en los
        datos deben incluirse en la salida de _parse_csv_records (completitud).

        **Validates: Requirements 2.5, 10.5**
        """
        # Asegurar IDs únicos
        enabled_ids_set = {u.user_id for u in enabled_users}
        disabled_ids_set = {u.user_id for u in disabled_users}
        assume(enabled_ids_set.isdisjoint(disabled_ids_set))

        # Construir CSV con registros de ambos tipos de usuarios
        all_user_ids = list(enabled_ids_set) + list(disabled_ids_set)
        csv_content = _build_csv_content(all_user_ids)

        # Parsear con solo los IDs habilitados
        records = _parse_csv_records(csv_content, enabled_ids_set)

        # Verificar que todos los IDs habilitados tienen registros en la salida
        returned_uids = {r["_normalized_user_id"] for r in records}
        for uid in enabled_ids_set:
            assert uid in returned_uids, (
                f"Usuario Enabled con ID '{uid}' debería tener registros en la "
                f"salida pero no se encontró. IDs retornados: {returned_uids}"
            )

    @given(
        enabled_users=st.lists(enabled_user_strategy, min_size=1, max_size=8),
        disabled_users=st.lists(disabled_user_strategy, min_size=0, max_size=8),
    )
    @settings(max_examples=150)
    def test_todos_los_registros_de_usuarios_enabled_se_incluyen_en_json(
        self, enabled_users: List[User], disabled_users: List[User]
    ):
        """
        Todos los registros que pertenecen a usuarios Enabled y existen en los
        datos deben incluirse en la salida de _parse_json_gz_records (completitud).

        **Validates: Requirements 2.5, 10.5**
        """
        # Asegurar IDs únicos
        enabled_ids_set = {u.user_id for u in enabled_users}
        disabled_ids_set = {u.user_id for u in disabled_users}
        assume(enabled_ids_set.isdisjoint(disabled_ids_set))

        # Construir datos JSON con registros de ambos tipos de usuarios
        all_user_ids = list(enabled_ids_set) + list(disabled_ids_set)
        json_data = _build_json_gz_data(all_user_ids)

        # Parsear con solo los IDs habilitados
        records = _parse_json_gz_records(json_data, enabled_ids_set)

        # Verificar que todos los IDs habilitados tienen registros en la salida
        returned_uids = {r["_normalized_user_id"] for r in records}
        for uid in enabled_ids_set:
            assert uid in returned_uids, (
                f"Usuario Enabled con ID '{uid}' debería tener registros en la "
                f"salida JSON pero no se encontró. IDs retornados: {returned_uids}"
            )
