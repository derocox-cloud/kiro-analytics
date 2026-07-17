"""Categorizador de prompts por tema basado en keywords.

Asigna a cada prompt la primera categoría cuyas keywords coincidan
(case-insensitive, subcadena) en orden de prioridad definido en PROMPT_CATEGORIES.
Si ninguna keyword coincide, se asigna la categoría "Otros".
"""
from __future__ import annotations

from typing import Dict, List

from src.models import PROMPT_CATEGORIES
from src.utils.text_utils import clean_metadata


def categorize_prompts(prompts: List[dict]) -> Dict[str, int]:
    """
    Categoriza una lista de prompts por tema según keywords.

    Para cada prompt, limpia la metadata interna del texto y luego
    evalúa las keywords de cada categoría en orden de prioridad.
    Asigna la primera categoría cuyas keywords produzcan una coincidencia
    case-insensitive por subcadena. Si ninguna coincide, asigna "Otros".

    Args:
        prompts: Lista de diccionarios con al menos la clave "text"
                 conteniendo el texto del prompt.

    Returns:
        Diccionario con categorías como claves y conteos como valores.
    """
    # Inicializar conteos para todas las categorías posibles
    counts: Dict[str, int] = {}

    for prompt in prompts:
        category = _classify_single_prompt(prompt)
        counts[category] = counts.get(category, 0) + 1

    return counts


def _classify_single_prompt(prompt: dict) -> str:
    """
    Clasifica un prompt individual en una categoría.

    Limpia la metadata interna del texto y busca la primera categoría
    cuyas keywords coincidan por subcadena (case-insensitive).

    Args:
        prompt: Diccionario con al menos la clave "text".

    Returns:
        Nombre de la categoría asignada, o "Otros" si ninguna coincide.
    """
    text = prompt.get("text", "")

    # Limpiar metadata interna antes de evaluar keywords
    cleaned_text = clean_metadata(text)

    # Convertir a minúsculas para búsqueda case-insensitive
    cleaned_lower = cleaned_text.lower()

    # Evaluar categorías en orden de prioridad (el orden del dict es estable en Python 3.7+)
    for category, keywords in PROMPT_CATEGORIES.items():
        for keyword in keywords:
            if keyword.lower() in cleaned_lower:
                return category

    return "Otros"
