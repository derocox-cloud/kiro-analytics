# Kiro Analytics Pipeline

<p align="center">
  <img src="examples/sample-report-preview.png" alt="Kiro Analytics" width="600">
</p>

<p align="center">
  Serverless analytics pipeline for <a href="https://kiro.dev">Kiro</a> usage tracking on AWS.<br>
  Pipeline de analítica serverless para seguimiento de uso de <a href="https://kiro.dev">Kiro</a> en AWS.
</p>

---

## Documentation / Documentación

| Language | Link |
|----------|------|
| 🇬🇧 English | [**Read in English**](README_en.md) |
| 🇪🇸 Español | [**Leer en Español**](README_es.md) |

---

## Quick Overview / Resumen Rápido

- Weekly & monthly HTML/CSV reports | Reportes semanales y mensuales en HTML/CSV
- AI-powered prompt analysis with Amazon Bedrock | Análisis de prompts con IA mediante Amazon Bedrock
- Per-user metrics: credits, conversations, code lines | Métricas por usuario: créditos, conversaciones, líneas de código
- Automatic scheduling via EventBridge | Programación automática vía EventBridge
- Graceful degradation | Degradación elegante
- 461+ tests (unit, PBT, integration) | 461+ pruebas (unitarias, PBT, integración)

---

## Quick Start / Inicio Rápido

```bash
git clone https://github.com/derocox-cloud/kiro-analytics.git
cd kiro-analytics
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,cdk]"
pytest
```

For full instructions, select your language above.  
Para instrucciones completas, selecciona tu idioma arriba.

---

## License / Licencia

MIT
