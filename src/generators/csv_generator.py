"""
Generador de reportes en formato CSV.

Exporta métricas de usuarios procesados a un archivo CSV con las 16 columnas
especificadas en los requisitos del pipeline de analytics.
"""
import csv
import io
from typing import List

from src.models import ProcessingResult, UserMetrics


# Columnas exactas del CSV según requisito 5.4
CSV_COLUMNS: List[str] = [
    "username",
    "display_name",
    "email",
    "is_internal",
    "credits_used",
    "credits_monthly",
    "credits_pct",
    "conversations",
    "total_messages",
    "days_active",
    "clients_used",
    "chat_messages_sent",
    "ai_code_lines",
    "inline_suggestions",
    "inline_accepted",
    "prompt_count",
]


def _is_internal_user(user: UserMetrics) -> bool:
    """
    Determina si un usuario es interno.

    Todos los usuarios del roster son miembros internos del equipo,
    por lo que este campo siempre retorna True (consistente con el
    comportamiento del script original).
    """
    return True


def _build_csv_row(user: UserMetrics) -> dict:
    """
    Construye un diccionario con los valores de una fila CSV para un usuario.

    Args:
        user: Métricas del usuario a exportar.

    Returns:
        Diccionario con las 16 columnas del CSV.
    """
    return {
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "is_internal": _is_internal_user(user),
        "credits_used": user.credits_used,
        "credits_monthly": user.credits_monthly,
        "credits_pct": user.credits_pct,
        "conversations": user.conversations,
        "total_messages": user.total_messages,
        "days_active": user.days_active,
        "clients_used": len(user.clients_used),
        "chat_messages_sent": user.chat_messages_sent,
        "ai_code_lines": user.ai_code_lines,
        "inline_suggestions": user.inline_suggestions,
        "inline_accepted": user.inline_accepted,
        "prompt_count": user.prompt_count,
    }


def generate_csv(metrics: ProcessingResult, period: str, start_date: str, end_date: str) -> str:
    """
    Genera un reporte CSV con una fila por usuario procesado.

    Exporta exactamente 16 columnas según el requisito 5.4:
    username, display_name, email, is_internal, credits_used, credits_monthly,
    credits_pct, conversations, total_messages, days_active, clients_used,
    chat_messages_sent, ai_code_lines, inline_suggestions, inline_accepted,
    prompt_count.

    Args:
        metrics: Resultado del procesamiento con métricas por usuario.
        period: Periodo del reporte ("daily", "weekly", "monthly").
        start_date: Fecha de inicio del periodo (formato YYYY-MM-DD).
        end_date: Fecha de fin del periodo (formato YYYY-MM-DD).

    Returns:
        Contenido CSV como string con encabezado y una fila por usuario.
    """
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()

    for user in metrics.user_metrics:
        row = _build_csv_row(user)
        writer.writerow(row)

    return output.getvalue()
