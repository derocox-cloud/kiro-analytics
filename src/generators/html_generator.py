"""
Generador de reportes HTML auto-contenidos para Kiro Analytics.

Produce un documento HTML completo con CSS inline, JavaScript embebido
para ordenamiento de tablas, y navegación lateral. Sin dependencias externas.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from src.models import AIAnalysisResult, ProcessingResult, UserMetrics


def generate_html(
    metrics: ProcessingResult,
    ai_analysis: Optional[AIAnalysisResult],
    period: str,
    start_date: str,
    end_date: str,
    prompts_by_user: dict = None,
) -> str:
    """
    Genera un reporte HTML auto-contenido con todas las secciones requeridas.

    Args:
        metrics: Resultado del procesamiento con métricas por usuario.
        ai_analysis: Resultado del análisis AI (puede ser None o no disponible).
        period: Periodo del reporte ("daily", "weekly", "monthly").
        start_date: Fecha de inicio en formato YYYY-MM-DD.
        end_date: Fecha de fin en formato YYYY-MM-DD.

    Returns:
        String con el documento HTML completo.
    """
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Calcular KPIs globales
    kpis = _calculate_kpis(metrics)

    # Construir secciones
    html = _build_head(period, start_date, end_date)
    html += _build_sidebar(period, start_date, end_date)
    html += _build_main_open()
    html += _build_header(period, start_date, end_date, generated_at)
    html += _build_kpis_section(kpis)
    html += _build_top10_section(metrics.user_metrics)
    html += _build_categories_section(metrics.user_metrics)
    html += _build_intents_section(metrics.user_metrics)
    html += _build_models_section(metrics.user_metrics)
    html += _build_detail_table(metrics.user_metrics)
    html += _build_inactive_section(metrics.inactive_users)
    html += _build_ai_analysis_section(ai_analysis)
    html += _build_prompts_section(prompts_by_user or {}, metrics.user_metrics)
    html += _build_recommendations_section(metrics, kpis)
    html += _build_footer()

    return html


def _calculate_kpis(metrics: ProcessingResult) -> dict:
    """Calcula los KPIs globales a partir de las métricas procesadas."""
    active_users = [u for u in metrics.user_metrics if u.credits_used > 0]
    total_credits = sum(u.credits_used for u in metrics.user_metrics)
    total_messages = sum(u.total_messages for u in metrics.user_metrics)
    total_registered = metrics.total_users_processed
    active_count = len(active_users)

    adoption_rate = (
        f"{(active_count / total_registered * 100):.1f}%"
        if total_registered > 0
        else "0%"
    )

    return {
        "active_users": active_count,
        "total_registered": total_registered,
        "total_credits": total_credits,
        "avg_credits": round(total_credits / active_count, 1) if active_count else 0,
        "adoption_rate": adoption_rate,
        "total_messages": total_messages,
        "total_conversations": sum(u.conversations for u in metrics.user_metrics),
        "total_prompts": sum(u.prompt_count for u in metrics.user_metrics),
    }


def _build_head(period: str, start_date: str, end_date: str) -> str:
    """Construye el <head> con CSS inline y JavaScript embebido."""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kiro Usage Report - {start_date} a {end_date}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 0; background: #f0f2f5; color: #333; }}
  .layout {{ display: flex; min-height: 100vh; }}
  .sidebar {{ width: 220px; background: #232f3e; position: fixed; top: 0; left: 0; height: 100vh; overflow-y: auto; padding: 20px 0; z-index: 100; }}
  .sidebar h3 {{ color: #ff9900; font-size: 0.9em; padding: 0 16px; margin: 18px 0 8px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .sidebar a {{ display: block; color: #ccc; text-decoration: none; padding: 8px 16px; font-size: 0.85em; border-left: 3px solid transparent; transition: all 0.2s; }}
  .sidebar a:hover {{ background: #37475a; color: white; border-left-color: #ff9900; }}
  .sidebar .logo {{ color: white; font-size: 1.1em; font-weight: 700; padding: 0 16px 15px; border-bottom: 1px solid #37475a; margin-bottom: 10px; }}
  .main-content {{ margin-left: 220px; padding: 20px 30px; flex: 1; }}
  @media (max-width: 900px) {{ .sidebar {{ display: none; }} .main-content {{ margin-left: 0; padding: 15px; }} }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  .header {{ background: linear-gradient(135deg, #232f3e 0%, #37475a 100%); color: white; padding: 25px 30px; border-radius: 12px; margin-bottom: 20px; }}
  .header h1 {{ margin: 0 0 5px 0; font-size: 1.8em; }}
  .header .meta {{ color: #ccc; font-size: 0.9em; margin: 0; }}
  h2 {{ color: #232f3e; margin: 30px 0 10px; font-size: 1.3em; }}
  .card {{ background: white; border-radius: 10px; padding: 22px; margin: 12px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
  .kpi {{ text-align: center; padding: 18px 10px; background: linear-gradient(135deg, #f8f9ff 0%, #eef1ff 100%); border-radius: 10px; border: 1px solid #e0e4f0; }}
  .kpi-value {{ font-size: 1.9em; font-weight: 700; color: #232f3e; line-height: 1.2; }}
  .kpi-label {{ color: #666; font-size: 0.82em; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
  th {{ background: #232f3e; color: white; padding: 10px 6px; text-align: left; position: sticky; top: 0; }}
  td {{ padding: 7px 6px; border-bottom: 1px solid #eee; }}
  tr:hover {{ background: #f0f4ff; }}
  .bar-chart {{ display: flex; flex-direction: column; gap: 8px; }}
  .bar-row {{ display: flex; align-items: center; gap: 10px; }}
  .bar-label {{ width: 180px; text-align: right; font-size: 0.85em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .bar-track {{ flex: 1; background: #f0f0f0; border-radius: 6px; height: 28px; position: relative; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 6px; display: flex; align-items: center; padding-left: 8px; color: white; font-size: 0.8em; font-weight: 600; min-width: 40px; transition: width 0.3s; }}
  .bar-value {{ width: 90px; text-align: right; font-size: 0.85em; font-weight: 600; }}
  .cat-row {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; }}
  .cat-dot {{ width: 14px; height: 14px; border-radius: 3px; flex-shrink: 0; }}
  .cat-name {{ width: 200px; font-size: 0.9em; }}
  .cat-bar-track {{ flex: 1; background: #f0f0f0; border-radius: 4px; height: 22px; overflow: hidden; }}
  .cat-bar-fill {{ height: 100%; border-radius: 4px; display: flex; align-items: center; padding-left: 6px; color: white; font-size: 0.75em; font-weight: 600; }}
  .cat-count {{ width: 50px; text-align: right; font-size: 0.85em; color: #666; }}
  .rec {{ padding: 12px 15px; margin: 8px 0; background: #fffbf0; border-left: 4px solid #ff9900; border-radius: 6px; font-size: 0.95em; }}
  .inactive-list {{ columns: 3; font-size: 0.85em; color: #888; }}
  .inactive-list span {{ display: block; padding: 2px 0; }}
  .section-badge {{ display: inline-block; background: #ff9900; color: white; font-size: 0.7em; padding: 2px 8px; border-radius: 10px; vertical-align: middle; margin-left: 8px; }}
  th.sortable {{ cursor: pointer; user-select: none; }}
  th.sortable:hover {{ background: #37475a; }}
  th.sortable::after {{ content: ' \\21C5'; font-size: 0.7em; opacity: 0.5; }}
  th.sortable.asc::after {{ content: ' \\25B2'; opacity: 1; }}
  th.sortable.desc::after {{ content: ' \\25BC'; opacity: 1; }}
</style>
<script>
function sortTable(th) {{
  var table = th.closest('table');
  var idx = Array.from(th.parentNode.children).indexOf(th);
  var body = table.querySelector('tbody') || table;
  var rows = Array.from(body.querySelectorAll('tr')).filter(function(r) {{ return !r.querySelector('th'); }});
  var asc = !th.classList.contains('asc');
  th.parentNode.querySelectorAll('th').forEach(function(h) {{ h.classList.remove('asc','desc'); }});
  th.classList.add(asc ? 'asc' : 'desc');
  rows.sort(function(a, b) {{
    var av = (a.children[idx] && a.children[idx].getAttribute('data-sort')) || (a.children[idx] ? a.children[idx].innerText.replace(/[,%$]/g,'').trim() : '');
    var bv = (b.children[idx] && b.children[idx].getAttribute('data-sort')) || (b.children[idx] ? b.children[idx].innerText.replace(/[,%$]/g,'').trim() : '');
    var an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
    return asc ? av.localeCompare(bv) : bv.localeCompare(av);
  }});
  rows.forEach(function(r) {{ body.appendChild(r); }});
}}
</script>
</head>
<body>
<div class="layout">
"""


def _build_sidebar(period: str, start_date: str, end_date: str) -> str:
    """Construye la barra de navegación lateral."""
    return f"""<nav class="sidebar">
  <div class="logo">&#128202; Kiro Analytics</div>
  <h3>Navegaci&oacute;n</h3>
  <a href="#kpis">KPIs Globales</a>
  <a href="#top-usuarios">Top Usuarios</a>
  <a href="#categorias">Categor&iacute;as de Prompts</a>
  <a href="#intenciones">Intenciones</a>
  <a href="#modelos">Distribuci&oacute;n de Modelos</a>
  <a href="#detalle">Detalle por Usuario</a>
  <a href="#inactivos">Usuarios Inactivos</a>
  <a href="#ai-analysis">An&aacute;lisis AI</a>
  <a href="#prompts">Muestras de Prompts</a>
  <a href="#recomendaciones">Recomendaciones</a>
  <h3>Info</h3>
  <a href="#" style="color:#999;pointer-events:none">{period.upper()}</a>
  <a href="#" style="color:#999;pointer-events:none">{start_date} a {end_date}</a>
</nav>
"""


def _build_main_open() -> str:
    """Abre el contenedor principal."""
    return """<div class="main-content">
<div class="container">
"""


def _build_header(period: str, start_date: str, end_date: str, generated_at: str) -> str:
    """Construye el encabezado del reporte."""
    return f"""<div class="header">
  <h1>&#128202; Kiro Usage Analytics Report</h1>
  <p class="meta">Periodo: {period.upper()} &nbsp;|&nbsp; {start_date} a {end_date} &nbsp;|&nbsp; Generado: {generated_at}</p>
</div>
"""


def _build_kpis_section(kpis: dict) -> str:
    """Construye la sección de KPIs globales."""
    return f"""<h2 id="kpis">Resumen General - KPIs Globales</h2>
<div class="card">
<div class="kpi-grid">
  <div class="kpi">
    <div class="kpi-value">{kpis['active_users']}<span style="font-size:0.5em;color:#999">/{kpis['total_registered']}</span></div>
    <div class="kpi-label">Usuarios Activos</div>
  </div>
  <div class="kpi">
    <div class="kpi-value">{kpis['adoption_rate']}</div>
    <div class="kpi-label">Tasa de Adopci&oacute;n</div>
  </div>
  <div class="kpi">
    <div class="kpi-value">{kpis['total_credits']:,.1f}</div>
    <div class="kpi-label">Cr&eacute;ditos Totales</div>
  </div>
  <div class="kpi">
    <div class="kpi-value">{kpis['avg_credits']:,.1f}</div>
    <div class="kpi-label">Promedio Cr&eacute;d./Usuario</div>
  </div>
  <div class="kpi">
    <div class="kpi-value">{kpis['total_messages']:,}</div>
    <div class="kpi-label">Mensajes Totales</div>
  </div>
  <div class="kpi">
    <div class="kpi-value">{kpis['total_conversations']:,}</div>
    <div class="kpi-label">Conversaciones</div>
  </div>
  <div class="kpi">
    <div class="kpi-value">{kpis['total_prompts']:,}</div>
    <div class="kpi-label">Prompts Analizados</div>
  </div>
</div>
</div>
"""


def _build_top10_section(user_metrics: list) -> str:
    """Construye la sección de top 10 usuarios por créditos consumidos."""
    sorted_users = sorted(user_metrics, key=lambda u: u.credits_used, reverse=True)
    top10 = sorted_users[:10]
    max_credits = top10[0].credits_used if top10 else 1

    html = """<h2 id="top-usuarios">Top 10 Usuarios por Cr&eacute;ditos</h2>
<div class="card">
<div class="bar-chart">
"""
    for u in top10:
        pct = (u.credits_used / max_credits * 100) if max_credits > 0 else 0
        label = u.display_name or u.username
        html += f"""  <div class="bar-row">
    <div class="bar-label">{_escape(label)}</div>
    <div class="bar-track"><div class="bar-fill" style="width:{max(pct, 3):.1f}%;background:#ff9900">{u.credits_used:,.1f}</div></div>
    <div class="bar-value">{u.total_messages} msgs</div>
  </div>
"""
    html += """</div>
</div>
"""
    return html


def _build_categories_section(user_metrics: list) -> str:
    """Construye la sección de categorización de prompts por tema."""
    # Agregar categorías de todos los usuarios
    all_categories: dict = {}
    for u in user_metrics:
        for cat, count in u.prompt_categories.items():
            all_categories[cat] = all_categories.get(cat, 0) + count

    if not all_categories:
        return """<h2 id="categorias">Categorizaci&oacute;n de Prompts</h2>
<div class="card"><p style="color:#999">Sin datos de prompts para este periodo.</p></div>
"""

    cat_colors = {
        "Código": "#ff6b35", "Infraestructura": "#004e89",
        "Base de Datos": "#1a936f", "Testing": "#c44536",
        "Documentación": "#3d5a80", "Refactoring": "#7b2d8e",
        "Frontend": "#f77f00", "Análisis": "#0096c7",
        "Configuración": "#6c757d", "Otros": "#adb5bd",
    }

    total_cat = sum(all_categories.values()) or 1
    max_cat = max(all_categories.values()) or 1

    html = """<h2 id="categorias">Categorizaci&oacute;n de Prompts</h2>
<div class="card">
"""
    for cat, count in sorted(all_categories.items(), key=lambda x: -x[1]):
        pct = count / max_cat * 100
        pct_total = count / total_cat * 100
        color = cat_colors.get(cat, "#adb5bd")
        html += f"""  <div class="cat-row">
    <div class="cat-dot" style="background:{color}"></div>
    <div class="cat-name">{_escape(cat)}</div>
    <div class="cat-bar-track"><div class="cat-bar-fill" style="width:{max(pct, 3):.1f}%;background:{color}">{pct_total:.0f}%</div></div>
    <div class="cat-count">{count}</div>
  </div>
"""
    html += """</div>
"""
    return html


def _build_intents_section(user_metrics: list) -> str:
    """Construye la sección de clasificación de intención (do/chat/spec)."""
    totals = {"do": 0, "chat": 0, "spec": 0}
    for u in user_metrics:
        for k in totals:
            totals[k] += u.intents.get(k, 0)
    total = sum(totals.values())
    if total == 0:
        return ""

    colors = {"do": "#ff6b35", "chat": "#0096c7", "spec": "#7b2d8e"}
    labels = {"do": "Acci&oacute;n (do)", "chat": "Consulta (chat)", "spec": "Spec/Dise&ntilde;o"}

    html = """<h2 id="intenciones">Clasificaci&oacute;n de Intenci&oacute;n</h2>
<div class="card">
<p style="color:#666;font-size:0.85em;margin-top:0">Distribuci&oacute;n de intenciones detectadas (chat = consultas, do = acciones de c&oacute;digo, spec = especificaciones)</p>
<div style="display:flex;gap:20px;align-items:center;margin:15px 0">"""
    for intent in ("do", "chat", "spec"):
        pct = totals[intent] / total * 100
        html += f"""<div style="flex:1;text-align:center">
    <div style="font-size:2em;font-weight:700;color:{colors[intent]}">{pct:.0f}%</div>
    <div style="font-size:0.85em;color:#666">{labels[intent]}</div>
    <div style="font-size:0.8em;color:#999">{totals[intent]:,} interacciones</div>
  </div>"""
    html += """</div>
<div style="background:#f0f0f0;border-radius:6px;height:30px;overflow:hidden;display:flex">"""
    for intent in ("do", "chat", "spec"):
        pct = totals[intent] / total * 100
        if pct > 0:
            html += f'<div style="width:{pct:.1f}%;background:{colors[intent]};display:flex;align-items:center;justify-content:center;color:white;font-size:0.75em;font-weight:600">{intent}</div>'
    html += f"""</div>
<p style="color:#999;font-size:0.8em;margin-bottom:0">Total: {total:,} clasificaciones</p>
</div>
"""
    return html


def _build_models_section(user_metrics: list) -> str:
    """Construye la sección de distribución de modelos AI."""
    all_models = {}
    for u in user_metrics:
        for model, count in u.models.items():
            all_models[model] = all_models.get(model, 0) + count
    if not all_models:
        return ""

    total = sum(all_models.values())
    colors = {
        "Auto": "#232f3e", "Claude Sonnet 4.5": "#ff6b35", "Claude Sonnet 4.6": "#e85d2f",
        "Claude Opus 4.6": "#7b2d8e", "Claude Opus 4.7": "#5e1d6e",
        "Claude Haiku 4.5": "#0096c7", "Claude Opus 4.1": "#4a1d6e",
    }

    html = """<h2 id="modelos">Distribuci&oacute;n de Modelos</h2>
<div class="card">
<p style="color:#666;font-size:0.85em;margin-top:0">Mensajes por modelo de IA utilizado en el periodo</p>
<div style="display:flex;gap:15px;flex-wrap:wrap;margin:15px 0">"""
    for model, count in sorted(all_models.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        color = colors.get(model, "#6c757d")
        html += f"""<div style="text-align:center;min-width:100px">
    <div style="font-size:1.6em;font-weight:700;color:{color}">{pct:.0f}%</div>
    <div style="font-size:0.8em;color:#666">{_escape(model)}</div>
    <div style="font-size:0.75em;color:#999">{count:,} msgs</div>
  </div>"""
    html += """</div>
<div style="background:#f0f0f0;border-radius:6px;height:30px;overflow:hidden;display:flex;margin:10px 0">"""
    for model, count in sorted(all_models.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        color = colors.get(model, "#6c757d")
        if pct >= 3:
            html += f'<div style="width:{pct:.1f}%;background:{color};display:flex;align-items:center;justify-content:center;color:white;font-size:0.7em;font-weight:600">{_escape(model)}</div>'
    html += """</div>
</div>
"""
    return html


def _build_prompts_section(prompts_by_user: dict, user_metrics: list) -> str:
    """Construye la sección de muestras de prompts por usuario."""
    if not prompts_by_user:
        return ""

    # Mapear user_id -> display_name
    names = {u.user_id: u.display_name for u in user_metrics}

    html = """<h2 id="prompts">Muestras de Prompts por Usuario</h2>
<div class="card">"""
    for uid, prompts in prompts_by_user.items():
        if not prompts:
            continue
        name = _escape(names.get(uid, uid[:8]))
        html += f'\n  <div style="font-weight:600;margin-top:12px;color:#232f3e">{name}:</div>'
        for p in prompts[:10]:
            text = p[:200] if isinstance(p, str) else p.get("prompt", "")[:200]
            safe = _escape(text)
            if safe.strip():
                html += f'\n  <div style="font-size:0.82em;color:#555;margin:3px 0 3px 15px;padding:4px 8px;background:#f8f9fa;border-radius:4px;border-left:3px solid #ff9900">{safe}&hellip;</div>'
    html += "\n</div>\n"
    return html


def _build_detail_table(user_metrics: list) -> str:
    """Construye la tabla detallada de métricas por usuario con ordenamiento."""
    sorted_users = sorted(user_metrics, key=lambda u: u.credits_used, reverse=True)
    count = len(sorted_users)

    html = f"""<h2 id="detalle">Detalle por Usuario <span class="section-badge">{count} usuarios</span></h2>
<div class="card" style="overflow-x:auto;">
<table>
<tr>
  <th class="sortable" onclick="sortTable(this)">#</th>
  <th class="sortable" onclick="sortTable(this)">Usuario</th>
  <th class="sortable" onclick="sortTable(this)">Nombre</th>
  <th class="sortable" onclick="sortTable(this)">Cr&eacute;d. Periodo</th>
  <th class="sortable" onclick="sortTable(this)">Cr&eacute;d. Mes</th>
  <th class="sortable" onclick="sortTable(this)">% Mes (1000)</th>
  <th class="sortable" onclick="sortTable(this)">Conv.</th>
  <th class="sortable" onclick="sortTable(this)">Msgs</th>
  <th class="sortable" onclick="sortTable(this)">D&iacute;as</th>
  <th>Clientes</th>
  <th class="sortable" onclick="sortTable(this)">L&iacute;neas AI</th>
  <th class="sortable" onclick="sortTable(this)">Inline</th>
  <th class="sortable" onclick="sortTable(this)">Prompts</th>
  <th>Top Categor&iacute;as</th>
</tr>
"""
    for i, u in enumerate(sorted_users, 1):
        inline_rate = (
            f"{u.inline_accepted}/{u.inline_suggestions}"
            if u.inline_suggestions > 0
            else "-"
        )
        top_cats = ", ".join(
            f"{k} ({v})"
            for k, v in sorted(u.prompt_categories.items(), key=lambda x: -x[1])[:2]
        ) if u.prompt_categories else "-"

        pct = u.credits_pct
        # Color de barra según porcentaje
        if pct >= 80:
            bar_color = "#dc3545"
        elif pct >= 50:
            bar_color = "#ff9900"
        elif pct >= 20:
            bar_color = "#0096c7"
        else:
            bar_color = "#adb5bd"

        # Color de fondo según nivel de uso
        bg = ""
        if pct >= 80:
            bg = ' style="background:#fff0f0"'
        elif u.credits_used < 5:
            bg = ' style="background:#f5f5f5;color:#999"'

        clients_str = ", ".join(u.clients_used) if u.clients_used else "-"

        html += f"""<tr{bg}>
  <td>{i}</td>
  <td>{_escape(u.username)}</td>
  <td>{_escape(u.display_name)}</td>
  <td style="text-align:right">{u.credits_used:,.2f}</td>
  <td style="text-align:right;font-weight:bold">{u.credits_monthly:,.2f}</td>
  <td style="min-width:120px" data-sort="{pct}"><div style="background:#f0f0f0;border-radius:4px;height:20px;overflow:hidden"><div style="width:{min(pct, 100):.1f}%;background:{bar_color};height:100%;border-radius:4px;display:flex;align-items:center;padding-left:4px;color:white;font-size:0.75em;font-weight:600;min-width:30px">{pct:.1f}%</div></div></td>
  <td style="text-align:center">{u.conversations}</td>
  <td style="text-align:center">{u.total_messages}</td>
  <td style="text-align:center">{u.days_active}</td>
  <td style="font-size:0.8em">{_escape(clients_str)}</td>
  <td style="text-align:right">{u.ai_code_lines:,}</td>
  <td style="text-align:center">{inline_rate}</td>
  <td style="text-align:center">{u.prompt_count}</td>
  <td style="font-size:0.8em">{_escape(top_cats)}</td>
</tr>
"""
    html += """</table>
</div>
"""
    return html


def _build_inactive_section(inactive_users: list) -> str:
    """Construye la sección de usuarios inactivos."""
    if not inactive_users:
        return """<h2 id="inactivos">Usuarios Inactivos</h2>
<div class="card"><p style="color:#999">Todos los usuarios registrados tuvieron actividad en este periodo.</p></div>
"""

    count = len(inactive_users)
    html = f"""<h2 id="inactivos">Usuarios Inactivos <span class="section-badge" style="background:#dc3545">{count} sin actividad</span></h2>
<div class="card">
<div class="inactive-list">
"""
    # inactive_users puede ser lista de User o lista de str
    for user in sorted(inactive_users, key=lambda u: u.display_name if hasattr(u, 'display_name') else str(u)):
        if hasattr(user, 'display_name'):
            html += f'  <span>&#128100; {_escape(user.display_name)} ({_escape(user.username)})</span>\n'
        else:
            html += f'  <span>&#128100; {_escape(str(user))}</span>\n'
    html += """</div>
</div>
"""
    return html


def _build_ai_analysis_section(ai_analysis: Optional[AIAnalysisResult]) -> str:
    """Construye la sección de análisis AI si está disponible."""
    if ai_analysis is None or not ai_analysis.available:
        return """<h2 id="ai-analysis">&#129302; An&aacute;lisis AI</h2>
<div class="card" style="border-left:4px solid #7b2d8e">
<p style="color:#999">An&aacute;lisis AI no disponible para este periodo.</p>
</div>
"""

    # Convertir el texto del análisis a HTML básico
    ai_html = _markdown_to_html(ai_analysis.analysis_text)
    model_info = f'<p style="color:#999;font-size:0.8em;margin-top:15px">Modelo: {_escape(ai_analysis.model_used)}</p>'

    return f"""<h2 id="ai-analysis">&#129302; An&aacute;lisis AI de Prompts</h2>
<div class="card" style="border-left:4px solid #7b2d8e">
{ai_html}
{model_info}
</div>
"""


def _build_recommendations_section(metrics: ProcessingResult, kpis: dict) -> str:
    """Construye la sección de recomendaciones basadas en las métricas."""
    recommendations = _generate_recommendations(metrics, kpis)

    html = """<h2 id="recomendaciones">Recomendaciones</h2>
<div class="card">
"""
    if not recommendations:
        html += '<p style="color:#999">Sin recomendaciones para este periodo.</p>\n'
    else:
        for rec in recommendations:
            html += f'  <div class="rec">{_escape(rec)}</div>\n'
    html += """</div>
"""
    return html


def _generate_recommendations(metrics: ProcessingResult, kpis: dict) -> list:
    """Genera recomendaciones basadas en el análisis de métricas."""
    recs = []

    # Recomendación sobre adopción
    active = kpis["active_users"]
    total = kpis["total_registered"]
    if total > 0:
        adoption_pct = active / total * 100
        if adoption_pct < 50:
            recs.append(
                f"La tasa de adopción es {adoption_pct:.0f}%. "
                f"Considerar sesiones de onboarding para los {total - active} usuarios inactivos."
            )

    # Recomendación sobre usuarios con alto consumo
    high_usage = [u for u in metrics.user_metrics if u.credits_pct >= 80]
    if high_usage:
        names = ", ".join(u.display_name or u.username for u in high_usage[:3])
        recs.append(
            f"{len(high_usage)} usuario(s) superan el 80% de créditos mensuales ({names}). "
            "Monitorear para evitar interrupciones de servicio."
        )

    # Recomendación sobre usuarios con baja actividad
    low_usage = [u for u in metrics.user_metrics if 0 < u.credits_used < 5]
    if low_usage:
        recs.append(
            f"{len(low_usage)} usuario(s) con uso mínimo (< 5 créditos). "
            "Ofrecer capacitación personalizada para incrementar adopción."
        )

    # Recomendación sobre inline suggestions
    total_suggestions = sum(u.inline_suggestions for u in metrics.user_metrics)
    total_accepted = sum(u.inline_accepted for u in metrics.user_metrics)
    if total_suggestions > 0:
        accept_rate = total_accepted / total_suggestions * 100
        if accept_rate < 30:
            recs.append(
                f"Tasa de aceptación de sugerencias inline: {accept_rate:.0f}%. "
                "Evaluar la calidad de las sugerencias o capacitar en su uso."
            )

    # Si no hay recomendaciones específicas
    if not recs:
        recs.append("El equipo muestra un uso saludable de Kiro. Continuar monitoreando tendencias.")

    return recs


def _build_footer() -> str:
    """Cierra el documento HTML."""
    return """</div>
</div>
</div>
</body>
</html>"""


def _escape(text: str) -> str:
    """Escapa caracteres HTML especiales."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _markdown_to_html(text: str) -> str:
    """Convierte texto con formato markdown básico a HTML."""
    if not text:
        return ""

    html = _escape(text)

    # Headers
    html = re.sub(r"^###\s+(.+)$", r"<h4>\1</h4>", html, flags=re.MULTILINE)
    html = re.sub(
        r"^##\s+(.+)$",
        r"<h3 style='margin-top:18px;color:#232f3e'>\1</h3>",
        html,
        flags=re.MULTILINE,
    )
    html = re.sub(
        r"^#\s+(.+)$",
        r"<h3 style='margin-top:18px;color:#7b2d8e'>\1</h3>",
        html,
        flags=re.MULTILINE,
    )

    # Bold
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)

    # Bullets
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(
        r"((?:<li>.*?</li>\n?)+)",
        r"<ul style='margin:4px 0'>\1</ul>",
        html,
    )

    # Horizontal rules
    html = html.replace("---", "<hr style='border:none;border-top:1px solid #eee;margin:12px 0'>")

    # Paragraphs
    html = re.sub(r"\n\n+", r"<br><br>", html)
    html = re.sub(r"(?<!>)\n(?!<)", r"<br>", html)

    return html
