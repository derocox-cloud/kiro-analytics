"""
Tests de propiedad (PBT) para la limpieza de metadata interna.

Utiliza Hypothesis para verificar que la función clean_metadata cumple con las
propiedades de correctitud definidas en el documento de diseño.

# Feature: aws-analytics-pipeline, Property 6: Limpieza de metadata interna
# Validates: Requirements 3.6, 4.2
"""
from __future__ import annotations

import re

from hypothesis import given, settings, strategies as st, assume

from src.utils.text_utils import clean_metadata


# =============================================================================
# Estrategias (Generators)
# =============================================================================

# Estrategia para texto plano sin patrones de metadata
texto_plano = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),  # Excluir surrogates
    ),
    min_size=0,
    max_size=500,
).filter(
    lambda t: not _contiene_metadata(t)
)

# Estrategia para generar bloques EnvironmentContext
contenido_environment = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="<>"),
    min_size=0,
    max_size=200,
)

bloques_environment_context = contenido_environment.map(
    lambda c: f"<EnvironmentContext>{c}</EnvironmentContext>"
)

# Estrategia para generar bloques source-event
contenido_source_event = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="<>"),
    min_size=0,
    max_size=200,
)

bloques_source_event = contenido_source_event.map(
    lambda c: f"<source-event>{c}</source-event>"
)

# Estrategia para generar secciones Included Rules
contenido_rules = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="#"),
    min_size=1,
    max_size=200,
)

secciones_included_rules = contenido_rules.map(
    lambda c: f"## Included Rules\n{c}"
)

# Estrategia para texto con metadata inyectada (al menos un patrón presente)
texto_con_metadata = st.one_of(
    # Texto con EnvironmentContext
    st.tuples(texto_plano, bloques_environment_context, texto_plano).map(
        lambda t: f"{t[0]}\n{t[1]}\n{t[2]}"
    ),
    # Texto con source-event
    st.tuples(texto_plano, bloques_source_event, texto_plano).map(
        lambda t: f"{t[0]}\n{t[1]}\n{t[2]}"
    ),
    # Texto con Included Rules
    st.tuples(texto_plano, secciones_included_rules).map(
        lambda t: f"{t[0]}\n{t[1]}"
    ),
    # Texto con múltiples patrones combinados
    st.tuples(
        texto_plano,
        bloques_environment_context,
        texto_plano,
        bloques_source_event,
        texto_plano,
    ).map(
        lambda t: f"{t[0]}\n{t[1]}\n{t[2]}\n{t[3]}\n{t[4]}"
    ),
)

# Estrategia para texto que NO contiene metadata (para probar preservación)
texto_sin_metadata = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),
        blacklist_characters="<>#",
    ),
    min_size=1,
    max_size=300,
).filter(
    lambda t: not _contiene_metadata(t) and t.strip() != ""
)


# =============================================================================
# Funciones auxiliares
# =============================================================================

# Patrones compilados para verificación
_RE_ENVIRONMENT_CONTEXT = re.compile(
    r"<EnvironmentContext>.*?</EnvironmentContext>", re.DOTALL
)
_RE_SOURCE_EVENT = re.compile(
    r"<source-event>.*?</source-event>", re.DOTALL
)
_RE_INCLUDED_RULES = re.compile(
    r"## Included Rules.*?(?=\n##(?! Included Rules)|\Z)", re.DOTALL
)


def _contiene_metadata(texto: str) -> bool:
    """Verifica si un texto contiene algún patrón de metadata interna."""
    if _RE_ENVIRONMENT_CONTEXT.search(texto):
        return True
    if _RE_SOURCE_EVENT.search(texto):
        return True
    if _RE_INCLUDED_RULES.search(texto):
        return True
    return False


def _tokens_no_whitespace(texto: str) -> set:
    """Extrae el conjunto de tokens no-whitespace de un texto."""
    return set(texto.split())


# =============================================================================
# Tests de propiedad
# =============================================================================

class TestProperty6LimpiezaMetadata:
    """
    Property 6: Limpieza de metadata interna.

    For any text string containing metadata patterns (EnvironmentContext tags,
    Included Rules sections, source-event tags), the cleaning function SHALL
    produce output that contains none of these patterns, AND for any text without
    metadata patterns, the cleaning function SHALL preserve the semantic content
    (non-whitespace tokens remain present).

    # Feature: aws-analytics-pipeline, Property 6: Limpieza de metadata interna
    # Validates: Requirements 3.6, 4.2
    """

    @given(texto=texto_con_metadata)
    @settings(max_examples=150)
    def test_limpieza_elimina_environment_context(self, texto: str):
        """
        Después de limpiar, el resultado NO contiene etiquetas EnvironmentContext.

        **Validates: Requirements 3.6, 4.2**
        """
        resultado = clean_metadata(texto)

        assert not _RE_ENVIRONMENT_CONTEXT.search(resultado), (
            f"El resultado aún contiene EnvironmentContext: {resultado[:200]}"
        )

    @given(texto=texto_con_metadata)
    @settings(max_examples=150)
    def test_limpieza_elimina_source_event(self, texto: str):
        """
        Después de limpiar, el resultado NO contiene etiquetas source-event.

        **Validates: Requirements 3.6, 4.2**
        """
        resultado = clean_metadata(texto)

        assert not _RE_SOURCE_EVENT.search(resultado), (
            f"El resultado aún contiene source-event: {resultado[:200]}"
        )

    @given(texto=texto_con_metadata)
    @settings(max_examples=150)
    def test_limpieza_elimina_included_rules(self, texto: str):
        """
        Después de limpiar, el resultado NO contiene secciones Included Rules.

        **Validates: Requirements 3.6, 4.2**
        """
        resultado = clean_metadata(texto)

        assert not _RE_INCLUDED_RULES.search(resultado), (
            f"El resultado aún contiene Included Rules: {resultado[:200]}"
        )

    @given(texto=texto_sin_metadata)
    @settings(max_examples=150)
    def test_preservacion_contenido_semantico(self, texto: str):
        """
        Para texto SIN patrones de metadata, la función preserva el contenido
        semántico: todos los tokens no-whitespace del original están presentes
        en el resultado.

        **Validates: Requirements 3.6, 4.2**
        """
        resultado = clean_metadata(texto)

        tokens_original = _tokens_no_whitespace(texto)
        tokens_resultado = _tokens_no_whitespace(resultado)

        # Todos los tokens del original deben estar en el resultado
        tokens_faltantes = tokens_original - tokens_resultado
        assert not tokens_faltantes, (
            f"Tokens perdidos después de limpiar texto sin metadata: {tokens_faltantes}"
        )

    @given(texto=texto_sin_metadata)
    @settings(max_examples=150)
    def test_idempotencia_texto_limpio(self, texto: str):
        """
        Limpiar un texto que ya está limpio (sin metadata) produce el mismo
        resultado. La función es idempotente.

        **Validates: Requirements 3.6, 4.2**
        """
        primera_limpieza = clean_metadata(texto)
        segunda_limpieza = clean_metadata(primera_limpieza)

        assert primera_limpieza == segunda_limpieza, (
            f"La función no es idempotente.\n"
            f"Primera limpieza: {primera_limpieza[:100]}\n"
            f"Segunda limpieza: {segunda_limpieza[:100]}"
        )

    @given(texto=texto_con_metadata)
    @settings(max_examples=150)
    def test_idempotencia_texto_con_metadata(self, texto: str):
        """
        Limpiar el resultado de una limpieza previa produce el mismo resultado.
        La función es idempotente incluso cuando el texto original tenía metadata.

        **Validates: Requirements 3.6, 4.2**
        """
        primera_limpieza = clean_metadata(texto)
        segunda_limpieza = clean_metadata(primera_limpieza)

        assert primera_limpieza == segunda_limpieza, (
            f"La función no es idempotente tras limpiar metadata.\n"
            f"Primera limpieza: {primera_limpieza[:100]}\n"
            f"Segunda limpieza: {segunda_limpieza[:100]}"
        )
