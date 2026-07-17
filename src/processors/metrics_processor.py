"""
Procesador de métricas por usuario para el pipeline de analytics.

Agrega datos crudos de las tres fuentes (user_report, by_user_analytic, prompt-metadata)
en métricas consolidadas por usuario. Calcula créditos mensuales acumulados,
porcentaje de uso, y detecta usuarios inactivos.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date
from typing import Dict, List, Set

from ..models import (
    CREDITS_PER_USER,
    CollectionResult,
    ProcessingResult,
    User,
    UserMetrics,
)
from ..processors.categorizer import categorize_prompts
from ..utils.text_utils import clean_metadata

logger = logging.getLogger(__name__)


def _get_enabled_users(roster: List[User]) -> Dict[str, User]:
    """Retorna diccionario de usuarios habilitados {user_id: User}."""
    return {user.user_id: user for user in roster if user.status == "Enabled"}


def _aggregate_user_reports(records: List[dict], start_date: date = None, end_date: date = None) -> Dict[str, dict]:
    """
    Agrega registros de user_report por usuario.

    Si start_date/end_date se proporcionan, solo agrega registros dentro del rango
    para las métricas de actividad (credits_used, conversations, messages, etc.).

    Campos extraídos: Credits_Used, Chat_Conversations, Total_Messages,
    Date (para días activos), Client_Type, y columnas *_messages (modelos).
    """
    data: Dict[str, dict] = defaultdict(lambda: {
        "credits": 0.0,
        "conversations": 0,
        "messages": 0,
        "days_active": set(),
        "clients": set(),
        "models": defaultdict(int),
    })

    start_str = start_date.isoformat() if start_date else ""
    end_str = end_date.isoformat() if end_date else ""

    for row in records:
        uid = row.get("_normalized_user_id", "")
        if not uid:
            continue

        # Filtrar por rango de fechas del periodo si se proporcionó
        date_val = row.get("Date", "")
        if start_str and date_val and date_val < start_str:
            continue
        if end_str and date_val and date_val > end_str:
            continue

        d = data[uid]
        d["credits"] += float(row.get("Credits_Used", 0) or 0)
        d["conversations"] += int(row.get("Chat_Conversations", 0) or 0)
        d["messages"] += int(row.get("Total_Messages", 0) or 0)

        if date_val:
            d["days_active"].add(date_val)

        client = row.get("Client_Type", "")
        if client:
            d["clients"].add(client)

        # Capturar columnas de modelos (*_messages excepto Total_Messages)
        for col, val in row.items():
            if col.endswith("_messages") and col != "Total_Messages":
                v = int(val) if val else 0
                if v > 0:
                    model_name = col.replace("_messages", "").replace("_", " ").title()
                    d["models"][model_name] += v

    return data


def _aggregate_analytics(records: List[dict]) -> Dict[str, dict]:
    """
    Agrega registros de by_user_analytic por usuario.

    Campos extraídos: Chat_MessagesSent, Chat_AICodeLines,
    Inline_SuggestionsCount, Inline_AcceptanceCount.
    """
    data: Dict[str, dict] = defaultdict(lambda: {
        "chat_messages_sent": 0,
        "ai_code_lines": 0,
        "inline_suggestions": 0,
        "inline_accepted": 0,
    })

    for row in records:
        uid = row.get("_normalized_user_id", "")
        if not uid:
            continue

        d = data[uid]
        d["chat_messages_sent"] += int(row.get("Chat_MessagesSent", 0) or 0)
        d["ai_code_lines"] += int(row.get("Chat_AICodeLines", 0) or 0)
        d["inline_suggestions"] += int(row.get("Inline_SuggestionsCount", 0) or 0)
        d["inline_accepted"] += int(row.get("Inline_AcceptanceCount", 0) or 0)

    return data


def _aggregate_prompts(records: List[dict]) -> Dict[str, List[dict]]:
    """
    Agrupa registros de prompt-metadata por usuario.

    Extrae prompt, timestamp, modelo y trigger de cada registro.
    """
    prompts_by_user: Dict[str, List[dict]] = defaultdict(list)

    for rec in records:
        uid = rec.get("_normalized_user_id", "")
        if not uid:
            continue

        req = rec.get("generateAssistantResponseEventRequest", {})
        prompt_text = req.get("prompt", "")

        if prompt_text and len(prompt_text.strip()) > 5:
            prompts_by_user[uid].append({
                "prompt": prompt_text[:300],
                "timestamp": req.get("timeStamp", ""),
                "model": req.get("modelId", ""),
                "trigger": req.get("chatTriggerType", ""),
            })

    return prompts_by_user


def _aggregate_intents(records: List[dict]) -> Dict[str, Dict[str, int]]:
    """
    Agrega clasificaciones de intención (chat/do/spec) por usuario.

    Filtra registros del modelo simple-task y extrae la intención dominante.
    """
    import json
    import re

    intents_by_user: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"chat": 0, "do": 0, "spec": 0, "total": 0}
    )

    for rec in records:
        uid = rec.get("_normalized_user_id", "")
        if not uid:
            continue

        req = rec.get("generateAssistantResponseEventRequest", {})
        if req.get("modelId") != "simple-task":
            continue

        resp = rec.get("generateAssistantResponseEventResponse", {})
        answer = resp.get("assistantResponse", "")

        try:
            match = re.search(r'\{[^}]*"chat"[^}]*\}', answer)
            if match:
                scores = json.loads(match.group())
                dominant = max(("chat", "do", "spec"), key=lambda k: scores.get(k, 0))
                intents_by_user[uid][dominant] += 1
                intents_by_user[uid]["total"] += 1
        except (json.JSONDecodeError, ValueError):
            continue

    return intents_by_user


def _calculate_monthly_credits(
    user_report_records: List[dict],
    end_date: date,
) -> Dict[str, float]:
    """
    Calcula créditos acumulados desde el día 1 del mes hasta end_date.

    Si los registros ya cubren desde el día 1 del mes (porque start_date es día 1
    del mismo mes que end_date), se usa directamente la suma de créditos.
    De lo contrario, se filtran los registros cuya fecha esté dentro del rango mensual.

    Args:
        user_report_records: Registros crudos de user_report con campo Date.
        end_date: Fecha de referencia (fin del periodo).

    Returns:
        Diccionario {user_id: créditos_acumulados_mes}.
    """
    month_start = end_date.replace(day=1)
    month_start_str = month_start.isoformat()
    end_date_str = end_date.isoformat()

    monthly_credits: Dict[str, float] = defaultdict(float)

    for row in user_report_records:
        uid = row.get("_normalized_user_id", "")
        if not uid:
            continue

        row_date = row.get("Date", "")
        # Filtrar registros dentro del rango mensual (día 1 hasta end_date)
        if row_date and month_start_str <= row_date <= end_date_str:
            monthly_credits[uid] += float(row.get("Credits_Used", 0) or 0)

    return monthly_credits


def process_metrics(
    raw_data: Dict[str, CollectionResult],
    roster: List[User],
    period: str,
    start_date: date,
    end_date: date,
) -> ProcessingResult:
    """
    Calcula métricas agregadas por usuario a partir de datos crudos.

    Procesa datos de las tres fuentes (user_report, by_user_analytic, prompt-metadata)
    y genera métricas consolidadas por usuario. Calcula créditos mensuales acumulados
    desde el día 1 del mes hasta end_date, porcentaje de uso sobre 1000 créditos,
    y detecta usuarios inactivos (Enabled sin registros en ninguna fuente).

    Args:
        raw_data: Diccionario con resultados de recolección por fuente.
            Claves esperadas: "user_report", "by_user_analytic", "prompt-metadata".
        roster: Lista de usuarios del roster.
        period: Periodo de ejecución ("daily", "weekly", "monthly").
        start_date: Fecha de inicio del rango.
        end_date: Fecha de fin del rango (fecha de referencia).

    Returns:
        ProcessingResult con métricas por usuario y lista de usuarios inactivos.
    """
    start_time = time.time()

    # Obtener usuarios habilitados del roster
    enabled_users = _get_enabled_users(roster)
    if not enabled_users:
        logger.warning("No hay usuarios habilitados en el roster.")
        return ProcessingResult(
            processing_duration_seconds=time.time() - start_time
        )

    # Extraer registros de cada fuente
    user_report_records = raw_data.get(
        "user_report", CollectionResult(source_type="user_report")
    ).records
    analytics_records = raw_data.get(
        "by_user_analytic", CollectionResult(source_type="by_user_analytic")
    ).records
    prompt_records = raw_data.get(
        "prompt-metadata", CollectionResult(source_type="prompt-metadata")
    ).records

    # Agregar datos por fuente
    user_reports = _aggregate_user_reports(user_report_records, start_date, end_date)
    analytics = _aggregate_analytics(analytics_records)
    prompts_by_user = _aggregate_prompts(prompt_records)
    intents_by_user = _aggregate_intents(prompt_records)

    # Calcular créditos mensuales acumulados (día 1 del mes hasta end_date)
    monthly_credits = _calculate_monthly_credits(user_report_records, end_date)

    # Determinar usuarios con actividad en alguna fuente
    active_user_ids: Set[str] = set()
    active_user_ids.update(user_reports.keys())
    active_user_ids.update(analytics.keys())
    active_user_ids.update(prompts_by_user.keys())

    # Filtrar solo usuarios habilitados del roster
    active_user_ids = active_user_ids & set(enabled_users.keys())

    # Construir métricas por usuario activo
    user_metrics_list: List[UserMetrics] = []

    for uid in sorted(active_user_ids):
        user = enabled_users[uid]
        ur = user_reports.get(uid, {
            "credits": 0.0,
            "conversations": 0,
            "messages": 0,
            "days_active": set(),
            "clients": set(),
            "models": defaultdict(int),
        })
        an = analytics.get(uid, {
            "chat_messages_sent": 0,
            "ai_code_lines": 0,
            "inline_suggestions": 0,
            "inline_accepted": 0,
        })
        user_prompts = prompts_by_user.get(uid, [])
        user_intents = intents_by_user.get(uid, {"chat": 0, "do": 0, "spec": 0, "total": 0})

        # Categorizar prompts del usuario
        user_categories = categorize_prompts(
            [{"text": p.get("prompt", "")} for p in user_prompts]
        ) if user_prompts else {}

        # Créditos del periodo y mensuales
        credits_used = round(ur["credits"], 2)
        credits_monthly_val = round(monthly_credits.get(uid, 0.0), 2)
        credits_pct = round(credits_monthly_val / CREDITS_PER_USER * 100, 1)

        # Clientes usados como lista ordenada
        clients = sorted(ur["clients"]) if ur["clients"] else []

        # Modelos usados
        models = dict(ur.get("models", {}))

        metrics = UserMetrics(
            user_id=uid,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            credits_used=credits_used,
            credits_monthly=credits_monthly_val,
            credits_pct=credits_pct,
            conversations=ur["conversations"],
            total_messages=ur["messages"],
            days_active=len(ur["days_active"]),
            clients_used=clients,
            chat_messages_sent=an["chat_messages_sent"],
            ai_code_lines=an["ai_code_lines"],
            inline_suggestions=an["inline_suggestions"],
            inline_accepted=an["inline_accepted"],
            prompt_count=len(user_prompts),
            prompt_categories=user_categories,
            intents=dict(user_intents),
            models=models,
        )
        user_metrics_list.append(metrics)

    # Detectar usuarios inactivos: Enabled sin registros en ninguna fuente
    inactive_users: List[User] = []
    for uid, user in enabled_users.items():
        if uid not in active_user_ids:
            inactive_users.append(user)
            # Incluir en métricas con valores 0 para que aparezcan en el reporte
            user_metrics_list.append(UserMetrics(
                user_id=uid,
                username=user.username,
                display_name=user.display_name,
                email=user.email,
                credits_used=0.0,
                credits_monthly=0.0,
                credits_pct=0.0,
                conversations=0,
                total_messages=0,
                days_active=0,
                clients_used=[],
                chat_messages_sent=0,
                ai_code_lines=0,
                inline_suggestions=0,
                inline_accepted=0,
                prompt_count=0,
                prompt_categories={},
                intents={},
                models={},
            ))

    # Ordenar métricas por créditos usados (descendente)
    user_metrics_list.sort(key=lambda m: m.credits_used, reverse=True)

    duration = time.time() - start_time

    logger.info(
        "Procesamiento completado: %d usuarios activos, %d inactivos (%.2fs)",
        len(user_metrics_list),
        len(inactive_users),
        duration,
    )

    return ProcessingResult(
        user_metrics=user_metrics_list,
        inactive_users=inactive_users,
        total_users_processed=len(user_metrics_list),
        processing_duration_seconds=duration,
    )


def lambda_handler(event: dict, context=None) -> dict:
    """Handler Lambda para Step Functions — procesa métricas agregadas."""
    import json
    import os
    from datetime import date as date_type

    import boto3

    from ..collectors.sources import read_roster_from_s3
    from ..utils.date_utils import get_date_range
    from ..utils.s3_utils import download_json

    reports_bucket = os.environ["REPORTS_BUCKET"]

    # Extraer params del state
    params = event.get("validation", {}).get("Payload", {}).get("params", {})
    if not params:
        params = event.get("validation", {}).get("params", {})
    if not params:
        params = event

    period = params["period"]
    reference_date = params["reference_date"]
    ref_date = date_type.fromisoformat(reference_date)
    start_date, end_date = get_date_range(period, ref_date)

    execution_id = f"{period}_{reference_date}"

    s3_client = boto3.client("s3")

    # Leer datos recolectados del S3 temporal
    raw_data = {}
    for source_type in ["user_report", "by_user_analytic", "prompt-metadata"]:
        temp_key = f"tmp/{execution_id}/{source_type}/data.json"
        try:
            records = download_json(s3_client, reports_bucket, temp_key)
            raw_data[source_type] = CollectionResult(
                source_type=source_type,
                records=records,
                file_count=1,
                data_size_bytes=0,
            )
        except Exception:
            raw_data[source_type] = CollectionResult(source_type=source_type)

    # Leer roster
    roster_s3_path = os.environ.get("ROSTER_S3_PATH", "")
    if roster_s3_path:
        parts = roster_s3_path.replace("s3://", "").split("/", 1)
        roster = read_roster_from_s3(s3_client, parts[0], parts[1])
    else:
        roster = []

    result = process_metrics(
        raw_data=raw_data,
        roster=roster,
        period=period,
        start_date=start_date,
        end_date=end_date,
    )

    # Persistir métricas en DynamoDB
    from .dynamodb_writer import persist_metrics

    try:
        persist_metrics(
            metrics=result.user_metrics,
            period=period,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        logger.warning("Error al persistir métricas en DynamoDB (continuando): %s", str(e))

    return {
        "users_processed": len(result.user_metrics),
        "inactive_users": len(result.inactive_users),
        "processing_duration_seconds": result.processing_duration_seconds,
    }
