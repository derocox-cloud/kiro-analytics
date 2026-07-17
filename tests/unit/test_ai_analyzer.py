"""Tests unitarios para el analizador AI con Bedrock."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.analyzers.ai_analyzer import (
    BEDROCK_TIMEOUT_SECONDS,
    MAX_RETRIES,
    MODEL_ID,
    _build_bedrock_request,
    _create_degraded_result,
    _prepare_payload,
    analyze_prompts,
)
from src.models import AIAnalysisResult, MAX_BEDROCK_CHARS, MAX_SAMPLES_PER_USER, User


# =============================================================================
# Tests para _prepare_payload
# =============================================================================


class TestPreparePayload:
    """Tests para la preparación del payload."""

    def _make_user(self, user_id: str, display_name: str) -> User:
        """Helper para crear un usuario de prueba."""
        return User(
            user_id=user_id,
            username=user_id,
            display_name=display_name,
            email=f"{user_id}@test.com",
            status="Enabled",
        )

    def test_payload_vacio_sin_prompts(self):
        """Retorna string vacío si no hay prompts."""
        result = _prepare_payload({}, {})
        assert result == ""

    def test_limpia_metadata_de_prompts(self):
        """Elimina metadata interna (EnvironmentContext, source-event) de los prompts."""
        users = {"u1": self._make_user("u1", "Usuario Uno")}
        prompts = {
            "u1": [
                "Hola <EnvironmentContext>secreto</EnvironmentContext> mundo"
            ]
        }
        result = _prepare_payload(prompts, users)
        assert "<EnvironmentContext>" not in result
        assert "secreto" not in result
        assert "Hola" in result
        assert "mundo" in result

    def test_limita_muestras_por_usuario(self):
        """No incluye más de MAX_SAMPLES_PER_USER prompts por usuario."""
        users = {"u1": self._make_user("u1", "Usuario Uno")}
        # Crear más prompts que el límite
        prompts = {"u1": [f"Prompt {i}" for i in range(MAX_SAMPLES_PER_USER + 10)]}
        result = _prepare_payload(prompts, users)

        # Contar cuántos "### Prompt" aparecen
        prompt_count = result.count("### Prompt")
        assert prompt_count <= MAX_SAMPLES_PER_USER

    def test_payload_no_excede_max_chars(self):
        """El payload total no excede MAX_BEDROCK_CHARS."""
        users = {}
        prompts = {}
        # Crear muchos usuarios con prompts largos
        for i in range(50):
            uid = f"user_{i}"
            users[uid] = self._make_user(uid, f"Usuario {i}")
            prompts[uid] = ["x" * 2000 for _ in range(15)]

        result = _prepare_payload(prompts, users)
        assert len(result) <= MAX_BEDROCK_CHARS

    def test_usa_display_name_del_usuario(self):
        """Usa el display_name del usuario en el encabezado."""
        users = {"u1": self._make_user("u1", "Juan Pérez")}
        prompts = {"u1": ["Hola mundo"]}
        result = _prepare_payload(prompts, users)
        assert "Juan Pérez" in result

    def test_usa_user_id_si_no_hay_usuario(self):
        """Usa el user_id como fallback si el usuario no está en el diccionario."""
        prompts = {"unknown_user": ["Hola mundo"]}
        result = _prepare_payload(prompts, {})
        assert "unknown_user" in result

    def test_multiples_usuarios(self):
        """Incluye secciones para múltiples usuarios."""
        users = {
            "u1": self._make_user("u1", "Usuario Uno"),
            "u2": self._make_user("u2", "Usuario Dos"),
        }
        prompts = {
            "u1": ["Prompt de usuario uno"],
            "u2": ["Prompt de usuario dos"],
        }
        result = _prepare_payload(prompts, users)
        assert "Usuario Uno" in result
        assert "Usuario Dos" in result


# =============================================================================
# Tests para _build_bedrock_request
# =============================================================================


class TestBuildBedrockRequest:
    """Tests para la construcción de la solicitud a Bedrock."""

    def test_estructura_basica(self):
        """Verifica la estructura básica de la solicitud."""
        request = _build_bedrock_request("contenido de prueba")
        assert request["modelId"] == MODEL_ID
        assert "messages" in request
        assert "system" in request
        assert "inferenceConfig" in request

    def test_contiene_payload_en_mensaje(self):
        """El payload aparece en el contenido del mensaje."""
        request = _build_bedrock_request("mi payload de prueba")
        messages = request["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        content = messages[0]["content"]
        assert any("mi payload de prueba" in block.get("text", "") for block in content)

    def test_configuracion_inferencia(self):
        """Verifica la configuración de inferencia."""
        request = _build_bedrock_request("test")
        config = request["inferenceConfig"]
        assert config["maxTokens"] == 2048
        assert config["temperature"] == 0.3


# =============================================================================
# Tests para _create_degraded_result
# =============================================================================


class TestCreateDegradedResult:
    """Tests para la creación de resultado degradado."""

    def test_resultado_degradado_no_disponible(self):
        """El resultado degradado tiene available=False."""
        result = _create_degraded_result("Error de prueba", 5.0)
        assert result.available is False

    def test_resultado_degradado_contiene_error(self):
        """El resultado degradado contiene el mensaje de error."""
        result = _create_degraded_result("Timeout en Bedrock", 10.0)
        assert result.error_message == "Timeout en Bedrock"

    def test_resultado_degradado_sin_tokens(self):
        """El resultado degradado tiene 0 tokens usados."""
        result = _create_degraded_result("Error", 1.0)
        assert result.tokens_used == 0

    def test_resultado_degradado_modelo_correcto(self):
        """El resultado degradado indica el modelo usado."""
        result = _create_degraded_result("Error", 1.0)
        assert result.model_used == MODEL_ID

    def test_resultado_degradado_duracion(self):
        """El resultado degradado registra la duración."""
        result = _create_degraded_result("Error", 42.5)
        assert result.duration_seconds == 42.5


# =============================================================================
# Tests para analyze_prompts
# =============================================================================


class TestAnalyzePrompts:
    """Tests para la función principal analyze_prompts."""

    def _make_user(self, user_id: str, display_name: str) -> User:
        """Helper para crear un usuario de prueba."""
        return User(
            user_id=user_id,
            username=user_id,
            display_name=display_name,
            email=f"{user_id}@test.com",
            status="Enabled",
        )

    def test_payload_vacio_retorna_resultado_disponible(self):
        """Si no hay prompts, retorna resultado disponible con mensaje informativo."""
        result = analyze_prompts({}, {})
        assert result.available is True
        assert "No hay prompts" in result.analysis_text
        assert result.tokens_used == 0

    @patch("src.analyzers.ai_analyzer.boto3.client")
    def test_invocacion_exitosa(self, mock_boto_client):
        """Una invocación exitosa retorna el análisis."""
        # Configurar mock
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        import io, json
        mock_body = io.BytesIO(json.dumps({
            "content": [{"text": "Análisis generado por AI"}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }).encode())
        mock_client.invoke_model.return_value = {"body": mock_body}

        users = {"u1": self._make_user("u1", "Test User")}
        prompts = {"u1": ["Cómo implementar una función en Python?"]}

        result = analyze_prompts(prompts, users)

        assert result.available is True
        assert result.analysis_text == "Análisis generado por AI"
        assert result.tokens_used == 150
        assert result.model_used == MODEL_ID
        assert result.error_message is None

    @patch("src.analyzers.ai_analyzer.time.sleep")
    @patch("src.analyzers.ai_analyzer.boto3.client")
    def test_degradacion_despues_de_reintentos(self, mock_boto_client, mock_sleep):
        """Retorna resultado degradado después de MAX_RETRIES fallos."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.invoke_model.side_effect = Exception("Timeout de Bedrock")

        users = {"u1": self._make_user("u1", "Test User")}
        prompts = {"u1": ["Un prompt de prueba"]}

        result = analyze_prompts(prompts, users)

        assert result.available is False
        assert "Timeout de Bedrock" in result.error_message
        assert result.tokens_used == 0
        # Verificar que se intentó MAX_RETRIES veces
        assert mock_client.invoke_model.call_count == MAX_RETRIES

    @patch("src.analyzers.ai_analyzer.time.sleep")
    @patch("src.analyzers.ai_analyzer.boto3.client")
    def test_exito_en_segundo_intento(self, mock_boto_client, mock_sleep):
        """Si falla el primer intento pero el segundo tiene éxito, retorna análisis."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        import io, json
        mock_body = io.BytesIO(json.dumps({
            "content": [{"text": "Análisis exitoso"}],
            "usage": {"input_tokens": 80, "output_tokens": 40},
        }).encode())
        mock_client.invoke_model.side_effect = [
            Exception("Error temporal"),
            {"body": mock_body},
        ]

        users = {"u1": self._make_user("u1", "Test User")}
        prompts = {"u1": ["Un prompt"]}

        result = analyze_prompts(prompts, users)

        assert result.available is True
        assert result.analysis_text == "Análisis exitoso"
        assert result.tokens_used == 120

    @patch("src.analyzers.ai_analyzer.boto3.client")
    def test_timeout_configurado(self, mock_boto_client):
        """Verifica que el cliente se configura con timeout de 60 segundos."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        import io, json
        mock_body = io.BytesIO(json.dumps({
            "content": [{"text": "OK"}],
            "usage": {"input_tokens": 5, "output_tokens": 5},
        }).encode())
        mock_client.invoke_model.return_value = {"body": mock_body}

        users = {"u1": self._make_user("u1", "Test")}
        prompts = {"u1": ["Prompt"]}

        analyze_prompts(prompts, users)

        # Verificar que boto3.client fue llamado con config que incluye timeout
        call_kwargs = mock_boto_client.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        assert config.read_timeout == BEDROCK_TIMEOUT_SECONDS
        assert config.connect_timeout == BEDROCK_TIMEOUT_SECONDS
