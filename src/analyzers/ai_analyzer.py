"""
Analizador AI con Amazon Bedrock.

Invoca Claude Haiku 4.5 para generar análisis inteligente de prompts
agrupados por usuario. Implementa limpieza de metadata, truncamiento
de payload, timeout y reintentos con degradación elegante.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Dict, List

import boto3
from botocore.config import Config

from src.models import (
    AIAnalysisResult,
    MAX_BEDROCK_CHARS,
    MAX_SAMPLES_PER_USER,
    User,
)
from src.utils.text_utils import clean_metadata

logger = logging.getLogger(__name__)

# Configuración del modelo Bedrock
MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
BEDROCK_TIMEOUT_SECONDS = 60
MAX_RETRIES = 3
BACKOFF_INTERVALS = [5, 10, 20]  # segundos entre reintentos


def _prepare_payload(
    prompts_by_user: Dict[str, List[str]],
    users: Dict[str, User],
) -> str:
    """
    Prepara el payload de prompts para enviar a Bedrock.

    Limpia metadata interna de cada prompt, limita a máximo 15 muestras
    por usuario y trunca el contenido total a 30,000 caracteres.

    Args:
        prompts_by_user: Diccionario {user_id: [textos de prompts]}.
        users: Diccionario {user_id: User} con información de usuarios.

    Returns:
        Texto formateado listo para enviar a Bedrock.
    """
    sections: List[str] = []
    total_chars = 0

    for user_id, prompts in prompts_by_user.items():
        # Obtener nombre del usuario para el encabezado
        user = users.get(user_id)
        display_name = user.display_name if user else user_id

        # Limitar a máximo MAX_SAMPLES_PER_USER muestras por usuario
        limited_prompts = prompts[:MAX_SAMPLES_PER_USER]

        # Limpiar metadata interna de cada prompt
        cleaned_prompts = [clean_metadata(p) for p in limited_prompts]

        # Construir sección del usuario
        user_section = f"## Usuario: {display_name}\n"
        for i, prompt in enumerate(cleaned_prompts, 1):
            entry = f"### Prompt {i}:\n{prompt}\n"
            # Verificar si agregar esta entrada excede el límite
            if total_chars + len(user_section) + len(entry) > MAX_BEDROCK_CHARS:
                break
            user_section += entry

        # Verificar si agregar esta sección excede el límite total
        if total_chars + len(user_section) > MAX_BEDROCK_CHARS:
            # Truncar la sección para que quepa dentro del límite
            remaining = MAX_BEDROCK_CHARS - total_chars
            if remaining > 0:
                sections.append(user_section[:remaining])
            break

        sections.append(user_section)
        total_chars += len(user_section)

    payload = "\n".join(sections)

    # Garantizar que el payload no exceda el límite absoluto
    if len(payload) > MAX_BEDROCK_CHARS:
        payload = payload[:MAX_BEDROCK_CHARS]

    return payload


def _build_bedrock_request(payload: str) -> dict:
    """
    Construye el cuerpo de la solicitud para Bedrock Converse API.

    Args:
        payload: Texto de prompts preparado para análisis.

    Returns:
        Diccionario con el cuerpo de la solicitud.
    """
    system_prompt = (
        "Eres un analista de productividad de desarrollo de software. "
        "Analiza los siguientes prompts de usuarios de un asistente de código AI (Kiro) "
        "y proporciona un resumen ejecutivo en español que incluya:\n"
        "1. Patrones de uso principales por usuario\n"
        "2. Temas más frecuentes\n"
        "3. Nivel de complejidad de las consultas\n"
        "4. Recomendaciones para mejorar la adopción\n"
        "5. Observaciones sobre la madurez del equipo en el uso de AI\n\n"
        "Sé conciso y enfocado en insights accionables."
    )

    return {
        "modelId": MODEL_ID,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"text": payload},
                ],
            }
        ],
        "system": [{"text": system_prompt}],
        "inferenceConfig": {
            "maxTokens": 2048,
            "temperature": 0.3,
        },
    }


def _invoke_bedrock(client, request_body: dict) -> dict:
    """
    Invoca Bedrock con el request body dado usando invoke_model API.

    Args:
        client: Cliente boto3 de bedrock-runtime.
        request_body: Cuerpo de la solicitud con modelId, messages, system, inferenceConfig.

    Returns:
        Respuesta de Bedrock parseada.

    Raises:
        Exception: Si la invocación falla.
    """
    import json as _json

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": request_body["inferenceConfig"]["maxTokens"],
        "system": request_body["system"][0]["text"],
        "messages": [
            {"role": m["role"], "content": m["content"][0]["text"]}
            for m in request_body["messages"]
        ],
    }

    response = client.invoke_model(
        modelId=request_body["modelId"],
        contentType="application/json",
        accept="application/json",
        body=_json.dumps(body),
    )

    result = _json.loads(response["body"].read())
    return {
        "output": {
            "message": {
                "content": result.get("content", []),
            },
        },
        "usage": {
            "inputTokens": result.get("usage", {}).get("input_tokens", 0),
            "outputTokens": result.get("usage", {}).get("output_tokens", 0),
        },
    }


def _create_degraded_result(error_message: str, duration: float) -> AIAnalysisResult:
    """
    Crea un resultado degradado cuando el análisis AI no está disponible.

    Args:
        error_message: Mensaje describiendo el error.
        duration: Duración total de los intentos en segundos.

    Returns:
        AIAnalysisResult con available=False.
    """
    return AIAnalysisResult(
        analysis_text="",
        available=False,
        model_used=MODEL_ID,
        tokens_used=0,
        duration_seconds=duration,
        error_message=error_message,
    )


def analyze_prompts(
    prompts_by_user: Dict[str, List[str]],
    users: Dict[str, User],
) -> AIAnalysisResult:
    """
    Analiza prompts agrupados por usuario usando Amazon Bedrock.

    Prepara el payload (limpio, truncado a 30K chars, max 15 muestras/usuario).
    Invoca Claude Haiku 4.5 con timeout de 60s.
    Retorna análisis o resultado degradado si falla después de 3 reintentos.

    Args:
        prompts_by_user: Diccionario {user_id: [textos de prompts]}.
        users: Diccionario {user_id: User} con información de usuarios.

    Returns:
        AIAnalysisResult con el análisis generado o resultado degradado.
    """
    start_time = time.time()

    # Preparar payload limpio y truncado
    payload = _prepare_payload(prompts_by_user, users)

    if not payload.strip():
        duration = time.time() - start_time
        return AIAnalysisResult(
            analysis_text="No hay prompts disponibles para analizar.",
            available=True,
            model_used=MODEL_ID,
            tokens_used=0,
            duration_seconds=duration,
        )

    # Construir solicitud para Bedrock
    request_body = _build_bedrock_request(payload)

    # Configurar cliente con timeout de 60 segundos
    bedrock_config = Config(
        read_timeout=BEDROCK_TIMEOUT_SECONDS,
        connect_timeout=BEDROCK_TIMEOUT_SECONDS,
        retries={"max_attempts": 0},  # Manejamos reintentos manualmente
    )
    client = boto3.client("bedrock-runtime", config=bedrock_config)

    # Intentar invocación con reintentos manuales
    last_error: str = ""
    for attempt in range(MAX_RETRIES):
        try:
            logger.info(
                "Invocando Bedrock (intento %d/%d)", attempt + 1, MAX_RETRIES
            )
            response = _invoke_bedrock(client, request_body)

            # Extraer texto de la respuesta
            output = response.get("output", {})
            message = output.get("message", {})
            content_blocks = message.get("content", [])
            analysis_text = ""
            for block in content_blocks:
                if "text" in block:
                    analysis_text += block["text"]

            # Extraer tokens usados
            usage = response.get("usage", {})
            tokens_used = usage.get("totalTokens", 0)
            if tokens_used == 0:
                tokens_used = usage.get("inputTokens", 0) + usage.get(
                    "outputTokens", 0
                )

            duration = time.time() - start_time
            return AIAnalysisResult(
                analysis_text=analysis_text,
                available=True,
                model_used=MODEL_ID,
                tokens_used=tokens_used,
                duration_seconds=duration,
            )

        except Exception as e:
            last_error = str(e)
            logger.warning(
                "Error en invocación Bedrock (intento %d/%d): %s",
                attempt + 1,
                MAX_RETRIES,
                last_error,
            )
            # Esperar con backoff antes del siguiente reintento
            if attempt < MAX_RETRIES - 1:
                wait_time = BACKOFF_INTERVALS[attempt]
                logger.info("Esperando %d segundos antes de reintentar...", wait_time)
                time.sleep(wait_time)

    # Todos los reintentos fallaron - retornar resultado degradado
    duration = time.time() - start_time
    error_msg = (
        f"Análisis AI no disponible después de {MAX_RETRIES} intentos. "
        f"Último error: {last_error}"
    )
    logger.error(error_msg)
    return _create_degraded_result(error_msg, duration)


def lambda_handler(event: dict, context=None) -> dict:
    """Handler Lambda para Step Functions — ejecuta análisis AI con Bedrock."""
    import os

    from src.collectors.sources import read_roster_from_s3
    from src.utils.s3_utils import download_json

    reports_bucket = os.environ.get("REPORTS_BUCKET", "")

    # Extraer params para construir execution_id determinístico
    params = event.get("validation", {}).get("Payload", {}).get("params", {})
    if not params:
        params = event.get("validation", {}).get("params", {})
    if not params:
        params = event
    period = params.get("period", "")
    reference_date = params.get("reference_date", "")
    execution_id = f"{period}_{reference_date}" if period else "manual"

    s3_client = boto3.client("s3")

    # Leer prompts del temporal
    prompts_by_user: Dict[str, List[str]] = {}
    try:
        temp_key = f"tmp/{execution_id}/prompt-metadata/data.json"
        records = download_json(s3_client, reports_bucket, temp_key)
        for record in records:
            uid = record.get("_normalized_user_id", "")
            # El prompt está en generateAssistantResponseEventRequest.prompt
            req = record.get("generateAssistantResponseEventRequest", {})
            prompt_text = req.get("prompt", "")
            if uid and prompt_text and len(prompt_text.strip()) > 5:
                prompts_by_user.setdefault(uid, []).append(prompt_text[:300])
    except Exception as e:
        logger.warning("No se pudieron leer prompts temporales: %s", e)

    # Leer roster para mapear user_ids a Users
    roster_s3_path = os.environ.get("ROSTER_S3_PATH", "")
    users: Dict[str, User] = {}
    if roster_s3_path:
        parts = roster_s3_path.replace("s3://", "").split("/", 1)
        roster = read_roster_from_s3(s3_client, parts[0], parts[1])
        users = {u.user_id: u for u in roster if u.status == "Enabled"}

    result = analyze_prompts(prompts_by_user, users)

    return {
        "available": result.available,
        "model_used": result.model_used,
        "tokens_used": result.tokens_used,
        "duration_seconds": result.duration_seconds,
        "analysis_text": result.analysis_text[:5000],  # Truncar para Step Functions
    }
