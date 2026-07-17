"""Tests unitarios para src/utils/text_utils.py"""
from __future__ import annotations

import pytest

from src.utils.text_utils import clean_metadata


class TestCleanMetadata:
    """Tests para clean_metadata."""

    def test_removes_environment_context(self):
        """Elimina bloques EnvironmentContext completos."""
        text = "Antes <EnvironmentContext>contenido interno</EnvironmentContext> Después"
        result = clean_metadata(text)
        assert "<EnvironmentContext>" not in result
        assert "contenido interno" not in result
        assert "Antes" in result
        assert "Después" in result

    def test_removes_multiline_environment_context(self):
        """Elimina bloques EnvironmentContext multilínea."""
        text = """Inicio
<EnvironmentContext>
línea 1
línea 2
línea 3
</EnvironmentContext>
Final"""
        result = clean_metadata(text)
        assert "<EnvironmentContext>" not in result
        assert "línea 1" not in result
        assert "Inicio" in result
        assert "Final" in result

    def test_removes_source_event(self):
        """Elimina tags source-event."""
        text = "Código <source-event>evento interno</source-event> más texto"
        result = clean_metadata(text)
        assert "<source-event>" not in result
        assert "evento interno" not in result
        assert "Código" in result
        assert "más texto" in result

    def test_removes_included_rules(self):
        """Elimina secciones Included Rules hasta el siguiente ##."""
        text = """# Título

## Included Rules (path/to/file.md) [Workspace]

Contenido de reglas que debe eliminarse.
Más contenido de reglas.

## Otra Sección

Contenido que debe preservarse."""
        result = clean_metadata(text)
        assert "Included Rules" not in result
        assert "Contenido de reglas" not in result
        assert "# Título" in result
        assert "## Otra Sección" in result
        assert "Contenido que debe preservarse" in result

    def test_removes_included_rules_at_end_of_text(self):
        """Elimina Included Rules cuando es la última sección."""
        text = """Contenido principal

## Included Rules (file.md) [Workspace]

Reglas que deben eliminarse.
Más reglas."""
        result = clean_metadata(text)
        assert "Included Rules" not in result
        assert "Reglas que deben eliminarse" not in result
        assert "Contenido principal" in result

    def test_removes_multiple_occurrences(self):
        """Maneja múltiples ocurrencias de cada patrón."""
        text = """<EnvironmentContext>ctx1</EnvironmentContext>
Texto medio
<EnvironmentContext>ctx2</EnvironmentContext>
<source-event>ev1</source-event>
Más texto
<source-event>ev2</source-event>"""
        result = clean_metadata(text)
        assert "<EnvironmentContext>" not in result
        assert "<source-event>" not in result
        assert "ctx1" not in result
        assert "ctx2" not in result
        assert "ev1" not in result
        assert "ev2" not in result
        assert "Texto medio" in result
        assert "Más texto" in result

    def test_preserves_text_without_patterns(self):
        """Texto sin patrones de metadata se preserva intacto."""
        text = "Este es un prompt normal sin metadata interna."
        result = clean_metadata(text)
        assert result == text

    def test_empty_string(self):
        """String vacío retorna string vacío."""
        assert clean_metadata("") == ""

    def test_handles_nested_environment_context(self):
        """Maneja contenido con tags HTML dentro de EnvironmentContext."""
        text = """Prompt
<EnvironmentContext>
<file name="test.py" />
<OPEN-EDITOR-FILES>
<file name="main.py" />
</OPEN-EDITOR-FILES>
</EnvironmentContext>
Continuación del prompt"""
        result = clean_metadata(text)
        assert "<EnvironmentContext>" not in result
        assert "OPEN-EDITOR-FILES" not in result
        assert "Prompt" in result
        assert "Continuación del prompt" in result

    def test_combined_patterns(self):
        """Elimina todos los patrones cuando aparecen juntos."""
        text = """Pregunta del usuario

<EnvironmentContext>
info del entorno
</EnvironmentContext>

## Included Rules (tech.md) [Workspace]

reglas de steering

## Contenido Real

El prompt real del usuario.

<source-event>metadata de evento</source-event>"""
        result = clean_metadata(text)
        assert "EnvironmentContext" not in result
        assert "info del entorno" not in result
        assert "Included Rules" not in result
        assert "reglas de steering" not in result
        assert "source-event" not in result
        assert "metadata de evento" not in result
        assert "Pregunta del usuario" in result
        assert "## Contenido Real" in result
        assert "El prompt real del usuario" in result
