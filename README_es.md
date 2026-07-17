# Kiro Usage Analytics

Pipeline de analítica serverless para el seguimiento de uso de [Kiro](https://kiro.dev) (asistente de codificación con IA), desplegado en AWS. Genera reportes semanales y mensuales de actividad del equipo incluyendo métricas de créditos, interacciones, categorización de prompts y análisis con IA mediante Amazon Bedrock.

![Vista previa del reporte de ejemplo](examples/sample-report-preview.png)

## Arquitectura

```
EventBridge (programación) → Step Functions (orquestación)
  ├── Lambda Validador → valida parámetros
  ├── Lambda Recolectores (x3 en paralelo) → lee logs de S3
  ├── Lambda Procesador → agrega métricas → persiste en DynamoDB
  ├── Lambda Analizador IA → invoca Bedrock Claude Haiku 4.5
  ├── Lambda Generador de Reportes → HTML/CSV → S3 + URLs pre-firmadas
  ├── Lambda Publicador → sitio web CloudFront
  └── Lambda Notificador → SNS → email
```

### Servicios AWS Utilizados

| Servicio | Propósito |
|----------|-----------|
| Lambda | 9 funciones independientes para cada etapa del pipeline |
| Step Functions | Orquestación con paralelismo, reintentos y degradación elegante |
| S3 | Fuente de logs, almacenamiento de reportes, sitio web estático |
| DynamoDB | Persistencia de métricas procesadas (bajo demanda) |
| EventBridge | Programación automática (semanal/mensual) |
| Bedrock | Análisis con IA de prompts con Claude Haiku 4.5 |
| CloudFront | Distribución web protegida con Basic Auth |
| SNS | Notificaciones por email |
| CloudWatch | Logs, métricas personalizadas, alarmas |

---

## Características

- Reportes semanales y mensuales en HTML y CSV (diarios bajo demanda)
- Métricas por usuario: créditos, conversaciones, mensajes, líneas de código IA, completados inline
- Categorización de prompts por tema (Código, Infraestructura, Base de Datos, Testing, Frontend, etc.)
- Clasificación de intención (do/chat/spec) y distribución de modelos de IA
- Análisis de prompts con IA usando Claude Haiku 4.5 vía Bedrock (API `invoke_model`)
- Identificación de usuarios inactivos y recomendaciones de adopción
- Cálculo de uso mensual contra el límite de 1,000 créditos/usuario de Kiro Pro
- Programación automática: semanal (viernes) y mensual (día 1) vía EventBridge
- Publicación web con Basic Auth vía CloudFront
- Notificaciones por email (éxito/fallo) vía SNS
- Persistencia histórica en DynamoDB
- Degradación elegante: reportes parciales si Bedrock o la publicación fallan
- Muestras de prompts por usuario en el reporte HTML

---

## Importante: Suscripción de Kiro vía Consola AWS

> ⚠️ **Esta solución está diseñada para suscripciones de Kiro creadas y administradas a través de la Consola de AWS.** Si tu equipo usa suscripciones de Kiro aprovisionadas mediante la Consola de Administración de AWS, los logs de uso se almacenan en buckets de S3 dentro de tu cuenta de AWS, que es lo que este pipeline lee.

### Habilitar Almacenamiento de Logs (Requerido)

Antes de desplegar este pipeline, debes habilitar el almacenamiento de logs en la Consola de AWS dentro de la configuración de tu suscripción de Kiro:

1. **Registro de Prompts** — Registra los prompts de Kiro junto con metadatos. Esto captura el contenido del prompt, intención, modelo usado y metadatos de respuesta en S3.

2. **Reporte de Actividad de Usuarios de Kiro** — Recopila métricas de actividad de usuarios y crea reportes diarios en un bucket de S3. Esto genera reportes CSV por usuario con consumo de créditos, conversaciones, mensajes y otras métricas de uso.

Ambas configuraciones deben estar habilitadas para que el pipeline tenga datos que procesar. Una vez activadas, los logs comenzarán a acumularse en tu bucket de S3 (formato: `dev-logs-prompt-kiro-<ACCOUNT_ID>-<REGION>-an`).

Para habilitarlos:
- Ve a **Consola AWS → Kiro → Configuración → Logging**
- Activa tanto **Registro de prompts** como **Reporte de actividad de usuarios**
- Confirma el bucket de S3 donde se almacenarán los logs

---

## Prerrequisitos

### Software

- Python 3.9+ (recomendado 3.13)
- AWS CDK CLI v2 (`npm install -g aws-cdk`)
- AWS CLI v2 configurado con credenciales
- Node.js 18+ (requerido por CDK CLI)

### Acceso AWS

- Cuenta de AWS con permisos para crear: Lambda, Step Functions, DynamoDB, S3, EventBridge, SNS, CloudFront, roles IAM, CloudWatch
- Acceso al bucket de logs de Kiro (formato: `dev-logs-prompt-kiro-<ACCOUNT_ID>-<REGION>-an`)
- Permisos de Bedrock para el modelo `us.anthropic.claude-haiku-4-5-20251001-v1:0`

---

## Instalación

```bash
# Clonar el repositorio
git clone https://github.com/derocox-cloud/kiro-analytics.git
cd kiro-analytics

# Crear entorno virtual
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependencias (desarrollo + CDK)
pip install -e ".[dev,cdk]"
```

### Verificar instalación

```bash
# Ejecutar todas las pruebas (461+)
pytest

# Solo pruebas unitarias
pytest tests/unit/

# Solo pruebas basadas en propiedades
pytest tests/pbt/

# Solo pruebas de integración
pytest tests/integration/
```

---

## Configuración

### 1. Configurar parámetros del stack

Edita `infrastructure/app.py` con tus valores de producción:

```python
config = StackConfig(
    logs_bucket="dev-logs-prompt-kiro-<ACCOUNT_ID>-<REGION>-an",
    account_id="<ACCOUNT_ID>",
    region="us-east-1",
    notification_emails=["admin@tu-empresa.com"],
    authorized_emails=["equipo@tu-empresa.com"],
    bedrock_model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    python_runtime="python3.13",
    log_retention_days=30,
    report_retention_days=90,
)
```

### 2. Preparar el roster de usuarios

El roster define qué usuarios se incluyen en los reportes. Formato CSV:

```csv
Username,Display name,Status,Email,User ID
jdoe,John Doe,Enabled,jdoe@empresa.com,uuid-001
jsmith,Jane Smith,Enabled,jsmith@empresa.com,uuid-002
inactivo,Usuario Inactivo,Disabled,inactivo@empresa.com,uuid-003
```

- Solo los usuarios con `Status=Enabled` son procesados
- El archivo se lee de S3 en cada ejecución (actualizable sin redespliegue)
- Ubicación por defecto: `s3://<reports-bucket>/config/kiro-users-dev.csv`

### 3. Habilitar acceso a Bedrock

Verifica que Claude Haiku 4.5 esté habilitado en tu región:

```bash
aws bedrock list-foundation-models \
  --query "modelSummaries[?modelId=='anthropic.claude-haiku-4-5-20251001-v1:0']" \
  --region us-east-1
```

Si no aparece listado, habilítalo desde la Consola AWS → Bedrock → Acceso a modelos.

---

## Despliegue

### Paso 1: Bootstrap del entorno CDK (solo la primera vez)

```bash
cdk bootstrap aws://<ACCOUNT_ID>/us-east-1
```

### Paso 2: Sintetizar template (verificar sin desplegar)

```bash
PYTHONPATH=. cdk synth --app "python3 infrastructure/app.py"
```

### Paso 3: Desplegar el stack

```bash
PYTHONPATH=. cdk deploy KiroAnalyticsPipeline --app "python3 infrastructure/app.py"
```

### Paso 4: Confirmar suscripciones SNS

Cada destinatario recibirá un email de confirmación de SNS. Deben hacer clic en el enlace de confirmación para comenzar a recibir notificaciones.

### Paso 5: Subir roster a S3

```bash
aws s3 cp kiro-users.csv \
  s3://<REPORTS_BUCKET>/config/kiro-users-dev.csv
```

### Paso 6: Verificar con ejecución manual

```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:<ACCOUNT_ID>:stateMachine:kiro-analytics-pipeline \
  --input '{"period": "weekly", "reference_date": "2026-07-07", "ai_analysis": true}'
```

---

## Ejecución Manual

### Parámetros de Entrada

| Parámetro | Tipo | Requerido | Valores | Por defecto |
|-----------|------|-----------|---------|-------------|
| `period` | string | ✅ | `daily`, `weekly`, `monthly` | — |
| `reference_date` | string | ✅ | Formato `YYYY-MM-DD` | — |
| `ai_analysis` | boolean | ❌ | `true`, `false` | `true` |
| `output_format` | string | ❌ | `html`, `csv`, `both` | `both` |

### Ejemplos

```bash
STATE_MACHINE_ARN="arn:aws:states:us-east-1:<ACCOUNT_ID>:stateMachine:kiro-analytics-pipeline"

# Reporte semanal
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"period": "weekly", "reference_date": "2026-07-07"}'

# Reporte mensual
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"period": "monthly", "reference_date": "2026-06-01"}'

# Sin análisis de IA (más rápido, sin costo de Bedrock)
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"period": "weekly", "reference_date": "2026-07-07", "ai_analysis": false}'
```

---

## Programación Automática

Una vez desplegado, EventBridge ejecuta automáticamente:

| Programación | Frecuencia | Hora (UTC-5) | Período |
|--------------|------------|--------------|---------|
| Semanal | Viernes | 7:00 AM | `weekly` |
| Mensual | Día 1 | 7:00 AM | `monthly` |

---

## Degradación Elegante

| Componente que Falla | Comportamiento | Reporte Generado |
|----------------------|----------------|------------------|
| Bedrock (análisis IA) | Continúa sin IA | ✅ Sin sección de análisis IA |
| Publicación web | Continúa con indicador | ✅ Disponible vía URL pre-firmada |
| Notificación | Registra en CloudWatch | ✅ Pipeline marca éxito |
| Recolección (1 fuente) | Fallo total del pipeline | ❌ No se genera reporte |

---

## Estructura del Proyecto

```
kiro-analytics/
├── src/                          # Código fuente del pipeline
│   ├── pipeline.py               # Punto de entrada (orquesta todas las etapas)
│   ├── models.py                 # Modelos de datos compartidos
│   ├── validators/               # Validación de entrada y roster
│   ├── collectors/               # Recolección de datos desde S3
│   ├── processors/               # Procesamiento y agregación de métricas
│   ├── analyzers/                # Análisis con IA usando Bedrock
│   ├── generators/               # Generación de reportes y publicación
│   ├── notifiers/                # Notificaciones SNS
│   ├── orchestrator/             # Handler Lambda y orquestación
│   └── utils/                    # Utilidades compartidas
├── infrastructure/               # AWS CDK (IaC)
│   ├── app.py                    # Punto de entrada CDK
│   ├── pipeline_stack.py         # Stack principal
│   └── state_machine.py         # Máquina de estados Step Functions
├── tests/                        # 461+ pruebas
│   ├── unit/                     # Pruebas unitarias
│   ├── pbt/                      # Pruebas basadas en propiedades (Hypothesis)
│   └── integration/              # Pruebas de integración (moto)
├── examples/                     # Salida de reporte de ejemplo
│   └── sample-report.html        # Reporte HTML de ejemplo con datos ficticios
└── pyproject.toml                # Dependencias y configuración del proyecto
```

---

## Reporte de Ejemplo

Un reporte HTML de ejemplo con datos ficticios está disponible en `examples/sample-report.html`. Ábrelo en tu navegador para previsualizar el formato del reporte incluyendo:

- Dashboard de KPIs
- Top 10 usuarios por créditos
- Distribución de categorías de prompts
- Clasificación de intenciones
- Uso de modelos de IA
- Tabla de detalle por usuario
- Usuarios inactivos
- Sección de análisis con IA
- Muestras de prompts
- Recomendaciones

---

## Costos Estimados (USD/mes)

| Servicio | Costo Estimado | Notas |
|----------|----------------|-------|
| Lambda | ~$1-5 | 9 funciones, ~90 ejecuciones/mes |
| Step Functions | ~$0.50 | ~90 transiciones de estado/mes |
| DynamoDB | ~$1-3 | Bajo demanda, ~3000 escrituras/mes |
| S3 | ~$0.50-2 | Almacenamiento de reportes + logs temporales |
| EventBridge | Gratis | Primeros 14M eventos incluidos |
| Bedrock | ~$5-20 | Depende del volumen de prompts analizados |
| CloudFront | ~$0.50-1 | Bajo tráfico (equipo interno) |
| SNS | ~$0.10 | ~90 emails/mes |
| CloudWatch | ~$1-3 | Logs + métricas + alarmas |
| **Total** | **~$10-35/mes** | Uso típico para equipo de 20-50 usuarios |

---

## Contribuir

¡Las contribuciones son bienvenidas! Por favor abre un issue o pull request.

## Licencia

MIT
