"""Utilidades de limpieza de texto para el pipeline de analytics."""
from __future__ import annotations

import re

# Patrones de metadata interna que se deben eliminar de los prompts
_ENVIRONMENT_CONTEXT_RE = re.compile(
    r"<EnvironmentContext>.*?</EnvironmentContext>",
    re.DOTALL,
)

_SOURCE_EVENT_RE = re.compile(
    r"<source-event>.*?</source-event>",
    re.DOTALL,
)

_INCLUDED_RULES_RE = re.compile(
    r"## Included Rules.*?(?=\n##(?! Included Rules)|\Z)",
    re.DOTALL,
)


def clean_metadata(text: str) -> str:
    """
    Elimina patrones de metadata interna del texto.

    Patrones eliminados:
    - EnvironmentContext: todo entre <EnvironmentContext> y </EnvironmentContext> (inclusive)
    - Included Rules: todo entre '## Included Rules' y el siguiente encabezado ## o fin del texto
    - source-event: patrones como <source-event>...</source-event>

    Maneja múltiples ocurrencias y patrones anidados.
    Preserva el resto del contenido del texto.
    """
    if not text:
        return text

    # Eliminar bloques EnvironmentContext (puede haber múltiples)
    result = _ENVIRONMENT_CONTEXT_RE.sub("", text)

    # Eliminar bloques source-event (puede haber múltiples)
    result = _SOURCE_EVENT_RE.sub("", result)

    # Eliminar secciones Included Rules (hasta el siguiente ## o fin del texto)
    result = _INCLUDED_RULES_RE.sub("", result)

    # Limpiar espacios en blanco excesivos resultantes de las eliminaciones
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = result.strip()

    return result
