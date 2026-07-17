"""
Tests de propiedad (PBT) para el truncamiento de payload enviado a Bedrock.

Utiliza Hypothesis para verificar que la función _prepare_payload cumple con
las restricciones de tamaño y muestras definidas en el documento de diseño.

# Feature: aws-analytics-pipeline, Property 7: Truncamiento de payload para Bedrock
# Validates: Requirements 4.3
"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.analyzers.ai_analyzer import _prepare_payload
from src.models import MAX_BEDROCK_CHARS, MAX_SAMPLES_PER_USER, User


# =============================================================================
# Estrategias (Generators)
# =============================================================================

# Estrategia para generar texto de prompt con longitud variable
prompt_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=5000,
)

# Estrategia para generar un user_id válido
user_ids = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=4,
    max_size=20,
)

# Estrategia para generar un diccionario de prompts por usuario con pocos usuarios
# y cantidad variable de prompts por usuario
prompts_by_user_small = st.dictionaries(
    keys=user_ids,
    values=st.lists(prompt_text, min_size=1, max_size=30),
    min_size=1,
    max_size=5,
)

# Estrategia para generar un diccionario con muchos usuarios y pocos prompts
prompts_by_user_many_users = st.dictionaries(
    keys=user_ids,
    values=st.lists(prompt_text, min_size=1, max_size=5),
    min_size=5,
    max_size=20,
)

# Estrategia para generar un diccionario con un solo usuario y muchos prompts
prompts_by_user_single_heavy = st.dictionaries(
    keys=user_ids,
    values=st.lists(prompt_text, min_size=15, max_size=50),
    min_size=1,
    max_size=1,
)

# Estrategia para generar prompts muy largos (cercanos al límite)
long_prompt_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=2000,
    max_size=10000,
)

prompts_by_user_long_prompts = st.dictionaries(
    keys=user_ids,
    values=st.lists(long_prompt_text, min_size=1, max_size=20),
    min_size=1,
    max_size=10,
)

# Estrategia general que combina todos los escenarios
prompts_by_user_general = st.one_of(
    prompts_by_user_small,
    prompts_by_user_many_users,
    prompts_by_user_single_heavy,
    prompts_by_user_long_prompts,
)


# =============================================================================
# Funciones auxiliares
# =============================================================================

def _build_users_dict(prompts_by_user: dict) -> dict:
    """
    Construye un diccionario de usuarios a partir de los user_ids presentes
    en prompts_by_user, simulando datos de roster.
    """
    users = {}
    for user_id in prompts_by_user:
        users[user_id] = User(
            user_id=user_id,
            username=f"user_{user_id[:8]}",
            display_name=f"Usuario {user_id[:8]}",
            email=f"{user_id[:8]}@example.com",
            status="Enabled",
        )
    return users


def _count_prompts_per_user_in_payload(payload: str) -> dict:
    """
    Cuenta cuántos prompts aparecen por usuario en el payload generado.

    Busca patrones '### Prompt N:' agrupados bajo '## Usuario: nombre'.
    Retorna un diccionario {display_name: conteo_prompts}.
    """
    counts = {}
    current_user = None

    for line in payload.split("\n"):
        if line.startswith("## Usuario: "):
            current_user = line[len("## Usuario: "):]
            if current_user not in counts:
                counts[current_user] = 0
        elif line.startswith("### Prompt ") and current_user is not None:
            counts[current_user] = counts.get(current_user, 0) + 1

    return counts


# =============================================================================
# Tests de propiedad
# =============================================================================

class TestProperty7TruncamientoPayload:
    """
    Property 7: Truncamiento de payload para Bedrock.

    For any collection of prompts grouped by user, the prepared payload SHALL
    never exceed 30,000 characters in total length AND SHALL never include more
    than 15 sample prompts per user, while maximizing the content included
    within these constraints.

    # Feature: aws-analytics-pipeline, Property 7: Truncamiento de payload para Bedrock
    **Validates: Requirements 4.3**
    """

    @given(prompts_by_user=prompts_by_user_general)
    @settings(max_examples=120)
    def test_payload_nunca_excede_max_bedrock_chars(
        self, prompts_by_user: dict
    ):
        """
        El payload preparado nunca debe exceder MAX_BEDROCK_CHARS (30,000)
        caracteres en longitud total, sin importar la cantidad o tamaño
        de los prompts de entrada.

        **Validates: Requirements 4.3**
        """
        users = _build_users_dict(prompts_by_user)
        payload = _prepare_payload(prompts_by_user, users)

        assert len(payload) <= MAX_BEDROCK_CHARS, (
            f"El payload tiene {len(payload)} caracteres, excede el límite "
            f"de {MAX_BEDROCK_CHARS}. Usuarios: {len(prompts_by_user)}, "
            f"prompts totales: {sum(len(v) for v in prompts_by_user.values())}"
        )

    @given(prompts_by_user=prompts_by_user_general)
    @settings(max_examples=120)
    def test_ningun_usuario_excede_max_samples_per_user(
        self, prompts_by_user: dict
    ):
        """
        Ningún usuario debe tener más de MAX_SAMPLES_PER_USER (15) prompts
        en el payload de salida, sin importar cuántos prompts tenga en la entrada.

        **Validates: Requirements 4.3**
        """
        users = _build_users_dict(prompts_by_user)
        payload = _prepare_payload(prompts_by_user, users)

        if not payload.strip():
            return  # Payload vacío es válido

        prompts_per_user = _count_prompts_per_user_in_payload(payload)

        for display_name, count in prompts_per_user.items():
            assert count <= MAX_SAMPLES_PER_USER, (
                f"El usuario '{display_name}' tiene {count} prompts en el "
                f"payload, excede el límite de {MAX_SAMPLES_PER_USER}"
            )

    @given(prompts_by_user=prompts_by_user_small)
    @settings(max_examples=120)
    def test_entrada_vacia_produce_payload_vacio(self, prompts_by_user: dict):
        """
        Una entrada con diccionario vacío produce un payload vacío.
        Una entrada con listas vacías de prompts produce un payload sin contenido
        de prompts.

        **Validates: Requirements 4.3**
        """
        # Caso especial: diccionario vacío
        users_empty: dict = {}
        payload_empty = _prepare_payload({}, users_empty)
        assert payload_empty == "", (
            f"Entrada vacía debería producir payload vacío, pero obtuvo: "
            f"'{payload_empty[:100]}'"
        )

    @given(prompts_by_user=prompts_by_user_single_heavy)
    @settings(max_examples=120)
    def test_un_usuario_con_muchos_prompts_respeta_limites(
        self, prompts_by_user: dict
    ):
        """
        Un solo usuario con muchos prompts (más de 15) debe respetar ambos
        límites: máximo 15 muestras y máximo 30,000 caracteres.

        **Validates: Requirements 4.3**
        """
        users = _build_users_dict(prompts_by_user)
        payload = _prepare_payload(prompts_by_user, users)

        # Verificar límite de caracteres
        assert len(payload) <= MAX_BEDROCK_CHARS, (
            f"Payload excede {MAX_BEDROCK_CHARS} chars con un solo usuario pesado"
        )

        # Verificar límite de muestras por usuario
        prompts_per_user = _count_prompts_per_user_in_payload(payload)
        for display_name, count in prompts_per_user.items():
            assert count <= MAX_SAMPLES_PER_USER, (
                f"Usuario '{display_name}' tiene {count} prompts, "
                f"excede límite de {MAX_SAMPLES_PER_USER}"
            )

    @given(prompts_by_user=prompts_by_user_long_prompts)
    @settings(max_examples=120)
    def test_prompts_muy_largos_respetan_limite_caracteres(
        self, prompts_by_user: dict
    ):
        """
        Prompts individuales muy largos (2000-10000 chars) deben ser truncados
        correctamente para que el payload total no exceda el límite.

        **Validates: Requirements 4.3**
        """
        users = _build_users_dict(prompts_by_user)
        payload = _prepare_payload(prompts_by_user, users)

        assert len(payload) <= MAX_BEDROCK_CHARS, (
            f"Payload con prompts largos tiene {len(payload)} chars, "
            f"excede límite de {MAX_BEDROCK_CHARS}"
        )

    @given(prompts_by_user=prompts_by_user_many_users)
    @settings(max_examples=120)
    def test_muchos_usuarios_con_pocos_prompts_respetan_limites(
        self, prompts_by_user: dict
    ):
        """
        Muchos usuarios (5-20) con pocos prompts cada uno deben respetar
        ambos límites en el payload combinado.

        **Validates: Requirements 4.3**
        """
        users = _build_users_dict(prompts_by_user)
        payload = _prepare_payload(prompts_by_user, users)

        # Verificar límite total de caracteres
        assert len(payload) <= MAX_BEDROCK_CHARS, (
            f"Payload con muchos usuarios tiene {len(payload)} chars, "
            f"excede límite de {MAX_BEDROCK_CHARS}"
        )

        # Verificar límite de muestras por usuario
        prompts_per_user = _count_prompts_per_user_in_payload(payload)
        for display_name, count in prompts_per_user.items():
            assert count <= MAX_SAMPLES_PER_USER, (
                f"Usuario '{display_name}' tiene {count} prompts, "
                f"excede límite de {MAX_SAMPLES_PER_USER}"
            )

    @given(prompts_by_user=prompts_by_user_general)
    @settings(max_examples=120)
    def test_payload_es_string_valido(self, prompts_by_user: dict):
        """
        El payload siempre debe ser un string válido (no None, no excepción).

        **Validates: Requirements 4.3**
        """
        users = _build_users_dict(prompts_by_user)
        payload = _prepare_payload(prompts_by_user, users)

        assert isinstance(payload, str), (
            f"El payload debe ser un string, pero es {type(payload)}"
        )
