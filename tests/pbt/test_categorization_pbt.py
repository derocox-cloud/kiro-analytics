"""
Tests de propiedad (PBT) para la categorización de prompts por tema.

Utiliza Hypothesis para verificar que el categorizador cumple con las propiedades
de correctitud definidas en el documento de diseño.

# Feature: aws-analytics-pipeline, Property 4: Categorización de prompts por prioridad de keywords
# Validates: Requirements 3.4
"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st, assume

from src.processors.categorizer import _classify_single_prompt, categorize_prompts
from src.models import PROMPT_CATEGORIES


# =============================================================================
# Constantes derivadas del modelo
# =============================================================================

# Orden de prioridad de categorías (según diseño)
PRIORITY_ORDER = list(PROMPT_CATEGORIES.keys())

# Todas las keywords agrupadas por categoría
ALL_KEYWORDS = {
    cat: keywords for cat, keywords in PROMPT_CATEGORIES.items()
}

# Lista plana de todas las keywords
FLAT_KEYWORDS = [kw for keywords in PROMPT_CATEGORIES.values() for kw in keywords]


def _categoria_esperada_para_keyword(keyword: str) -> str:
    """
    Determina la categoría que el categorizador asignará cuando una keyword
    está presente, considerando que el matching es por subcadena y prioridad.

    Si la keyword contiene como subcadena una keyword de una categoría de
    mayor prioridad, esa categoría de mayor prioridad ganará.
    """
    kw_lower = keyword.lower()
    for cat in PRIORITY_ORDER:
        for cat_kw in ALL_KEYWORDS[cat]:
            if cat_kw.lower() in kw_lower:
                return cat
    return "Otros"


def _keywords_puras_para_categoria(cat_idx: int) -> list[str]:
    """
    Retorna keywords de una categoría que NO contienen subcadenas de
    keywords de categorías con mayor prioridad.

    Estas keywords son 'puras' — al inyectarlas, solo activan su propia categoría.
    """
    categoria = PRIORITY_ORDER[cat_idx]
    keywords_puras = []
    for kw in ALL_KEYWORDS[categoria]:
        if _categoria_esperada_para_keyword(kw) == categoria:
            keywords_puras.append(kw)
    return keywords_puras


# Pre-calcular keywords puras por categoría
KEYWORDS_PURAS = {
    cat_idx: _keywords_puras_para_categoria(cat_idx)
    for cat_idx in range(len(PRIORITY_ORDER))
}

# Categorías que tienen al menos una keyword pura
CATEGORIAS_CON_KEYWORDS_PURAS = [
    idx for idx, kws in KEYWORDS_PURAS.items() if len(kws) > 0
]


# =============================================================================
# Estrategias (Generators)
# =============================================================================

def _no_contiene_keywords(text: str) -> bool:
    """Verifica que el texto no contenga ninguna keyword de ninguna categoría."""
    text_lower = text.lower()
    return not any(kw.lower() in text_lower for kw in FLAT_KEYWORDS)


safe_alphabet = st.characters(
    whitelist_categories=("L", "N", "Z"),
    whitelist_characters=" .,;:!?()-_\n",
    blacklist_characters="",
)

# Texto base sin keywords (para inyectar keywords controladamente)
texto_sin_keywords = st.text(
    alphabet=safe_alphabet, min_size=0, max_size=100
).filter(_no_contiene_keywords)

# Estrategia para seleccionar un índice de categoría con keywords puras
indice_categoria_pura = st.sampled_from(CATEGORIAS_CON_KEYWORDS_PURAS)

# Estrategia para seleccionar cualquier índice de categoría
indice_categoria = st.integers(min_value=0, max_value=len(PRIORITY_ORDER) - 1)


def keyword_con_case_aleatorio(keyword: str) -> st.SearchStrategy[str]:
    """Genera variaciones de case de una keyword."""
    variaciones = [
        keyword.lower(),
        keyword.upper(),
        keyword.capitalize(),
        keyword.swapcase(),
    ]
    # Agregar variación alternada
    alternada = "".join(
        c.upper() if i % 2 == 0 else c.lower()
        for i, c in enumerate(keyword)
    )
    variaciones.append(alternada)
    return st.sampled_from(variaciones)


# =============================================================================
# Tests de propiedad
# =============================================================================

class TestProperty4CategorizacionPrompts:
    """
    Property 4: Categorización de prompts por prioridad de keywords.

    For any prompt text, the categorization function SHALL assign the first
    category (in priority order: Código, Infraestructura, Base de Datos,
    Testing, Documentación, Refactoring, Frontend, Análisis, Configuración)
    whose keywords produce a case-insensitive substring match against the
    cleaned text; if no keywords match, it SHALL assign "Otros".

    # Feature: aws-analytics-pipeline, Property 4: Categorización de prompts por prioridad de keywords
    # Validates: Requirements 3.4
    """

    @given(
        base_text=texto_sin_keywords,
        cat_idx=indice_categoria_pura,
        data=st.data(),
    )
    @settings(max_examples=200)
    def test_keyword_inyectada_asigna_categoria_correcta(
        self, base_text: str, cat_idx: int, data
    ):
        """
        Cuando se inyecta una keyword pura de una categoría en un texto sin
        otras keywords, la función debe asignar esa categoría.

        **Validates: Requirements 3.4**
        """
        categoria = PRIORITY_ORDER[cat_idx]
        keywords_puras = KEYWORDS_PURAS[cat_idx]
        keyword = data.draw(st.sampled_from(keywords_puras))

        # Inyectar la keyword en el texto base
        texto = f"{base_text} {keyword} algo más"
        prompt = {"text": texto}

        resultado = _classify_single_prompt(prompt)

        assert resultado == categoria, (
            f"Con keyword '{keyword}' de categoría '{categoria}', "
            f"se esperaba '{categoria}' pero se obtuvo '{resultado}'. "
            f"Texto: '{texto}'"
        )

    @given(base_text=texto_sin_keywords)
    @settings(max_examples=150)
    def test_texto_sin_keywords_asigna_otros(self, base_text: str):
        """
        Texto que no contiene ninguna keyword de ninguna categoría
        siempre se asigna a "Otros".

        **Validates: Requirements 3.4**
        """
        prompt = {"text": base_text}
        resultado = _classify_single_prompt(prompt)

        assert resultado == "Otros", (
            f"Texto sin keywords debería ser 'Otros', pero fue '{resultado}'. "
            f"Texto: '{base_text}'"
        )

    @given(
        base_text=texto_sin_keywords,
        data=st.data(),
    )
    @settings(max_examples=200)
    def test_prioridad_categoria_mayor_gana(
        self, base_text: str, data
    ):
        """
        Cuando keywords de múltiples categorías están presentes, la categoría
        con mayor prioridad (menor índice en PRIORITY_ORDER) gana.

        **Validates: Requirements 3.4**
        """
        # Seleccionar dos categorías con keywords puras y diferente prioridad
        high_idx = data.draw(st.sampled_from(CATEGORIAS_CON_KEYWORDS_PURAS))
        low_idx = data.draw(st.sampled_from(CATEGORIAS_CON_KEYWORDS_PURAS))
        assume(high_idx < low_idx)

        cat_alta = PRIORITY_ORDER[high_idx]
        cat_baja = PRIORITY_ORDER[low_idx]

        kw_alta = data.draw(st.sampled_from(KEYWORDS_PURAS[high_idx]))
        kw_baja = data.draw(st.sampled_from(KEYWORDS_PURAS[low_idx]))

        # Poner la keyword de baja prioridad primero para verificar que el orden
        # en el texto no importa, solo el orden de prioridad de categorías
        texto = f"{base_text} {kw_baja} luego {kw_alta}"
        prompt = {"text": texto}

        resultado = _classify_single_prompt(prompt)

        assert resultado == cat_alta, (
            f"Con keywords '{kw_alta}' ({cat_alta}, prioridad {high_idx}) y "
            f"'{kw_baja}' ({cat_baja}, prioridad {low_idx}), "
            f"se esperaba '{cat_alta}' pero se obtuvo '{resultado}'. "
            f"Texto: '{texto}'"
        )

    @given(
        base_text=texto_sin_keywords,
        cat_idx=indice_categoria_pura,
        data=st.data(),
    )
    @settings(max_examples=200)
    def test_case_insensitive_keyword_match(
        self, base_text: str, cat_idx: int, data
    ):
        """
        Las keywords coinciden independientemente del case (mayúsculas/minúsculas).

        **Validates: Requirements 3.4**
        """
        categoria = PRIORITY_ORDER[cat_idx]
        keywords_puras = KEYWORDS_PURAS[cat_idx]
        keyword = data.draw(st.sampled_from(keywords_puras))

        # Generar variación de case
        variacion = data.draw(keyword_con_case_aleatorio(keyword))

        texto = f"{base_text} {variacion} fin"
        prompt = {"text": texto}

        resultado = _classify_single_prompt(prompt)

        assert resultado == categoria, (
            f"Keyword '{variacion}' (variación de '{keyword}') de categoría "
            f"'{categoria}' debería asignar '{categoria}', pero fue '{resultado}'. "
            f"Texto: '{texto}'"
        )

    @given(
        cat_idx=indice_categoria_pura,
        data=st.data(),
    )
    @settings(max_examples=150)
    def test_metadata_no_afecta_categorizacion(
        self, cat_idx: int, data
    ):
        """
        Keywords dentro de bloques de metadata (EnvironmentContext, Included Rules,
        source-event) NO deben afectar la categorización porque se limpian antes
        de evaluar.

        **Validates: Requirements 3.4**
        """
        categoria = PRIORITY_ORDER[cat_idx]
        keywords_puras = KEYWORDS_PURAS[cat_idx]
        keyword = data.draw(st.sampled_from(keywords_puras))

        # Generar texto donde la keyword SOLO aparece dentro de metadata
        metadata_variants = [
            f"<EnvironmentContext>contexto con {keyword} dentro</EnvironmentContext>",
            f"<source-event>evento con {keyword} aquí</source-event>",
            f"## Included Rules\nRegla con {keyword} incluida\n\n## Otra sección",
        ]
        metadata_block = data.draw(st.sampled_from(metadata_variants))

        # El texto visible no tiene keywords — usar prefijo/sufijo seguros
        texto = f"zzz qqq {metadata_block} yyy ppp"
        prompt = {"text": texto}

        resultado = _classify_single_prompt(prompt)

        # La keyword está solo en metadata, así que debería ser "Otros"
        assert resultado == "Otros", (
            f"Keyword '{keyword}' solo en metadata no debería categorizar, "
            f"pero se obtuvo '{resultado}'. Texto completo: '{texto}'"
        )

    @given(
        prompts_count=st.integers(min_value=1, max_value=10),
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_categorize_prompts_conteo_correcto(
        self, prompts_count: int, data
    ):
        """
        La función categorize_prompts retorna conteos que suman el total
        de prompts procesados.

        **Validates: Requirements 3.4**
        """
        prompts = []
        for _ in range(prompts_count):
            # Generar prompts con keywords aleatorias o sin keywords
            usar_keyword = data.draw(st.booleans())
            if usar_keyword:
                cat_idx = data.draw(indice_categoria_pura)
                kws = KEYWORDS_PURAS[cat_idx]
                kw = data.draw(st.sampled_from(kws))
                prompts.append({"text": f"zzz {kw} qqq"})
            else:
                prompts.append({"text": "zzz qqq xxx"})

        resultado = categorize_prompts(prompts)

        # La suma de todos los conteos debe ser igual al número de prompts
        total = sum(resultado.values())
        assert total == prompts_count, (
            f"La suma de conteos ({total}) no coincide con el número de "
            f"prompts ({prompts_count}). Resultado: {resultado}"
        )
