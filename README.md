# Kiro Analytics Pipeline

Pipeline serverless de análisis de uso de Kiro (asistente AI de codificación) desplegado en AWS. Genera reportes semanales y mensuales de actividad del equipo, incluyendo métricas de créditos, interacciones, categorización de prompts, y análisis AI con Amazon Bedrock.

## Arquitectura

```
EventBridge (programación) → Step Functions (orquestación)
  ├── Lambda Validador → valida parámetros
  ├── Lambda Recolectores (x3 en paralelo) → lee logs de S3
  ├── Lambda Procesador → agrega métricas → persiste en DynamoDB
  ├── Lambda Analizador AI → invoca Bedrock Claude Haiku 4.5
  ├── Lambda Generador Reportes → HTML/CSV → S3 + URLs pre-firmadas
  ├── Lambda Publicador → CloudFront sitio web
  └── Lambda Notificador → SNS → correo electrónico
```

### Servicios AWS utilizados

| Servicio | Uso |
|----------|-----|
| Lambda | 9 funciones independientes para cada etapa del pipeline |
| Step Functions | Orquestación con paralelismo, reintentos y degradación elegante |
| S3 | Fuente de logs, almacenamiento de reportes, sitio web estático |
| DynamoDB | Persistencia de métricas procesadas (on-demand) |
| EventBridge | Programación automática (semanal/mensual) |
| Bedrock | Análisis AI de prompts con Claude Haiku 4.5 |
| CloudFront | Distribución web protegida con Basic Auth |
| SNS | Notificaciones por correo electrónico |
| CloudWatch | Logs, métricas personalizadas, alarmas |

---

## Requisitos Previos

### Software

- Python 3.9+ (recomendado 3.13)
- AWS CDK CLI v2 (`npm install -g aws-cdk`)
- AWS CLI v2 configurado con credenciales
- Node.js 18+ (requerido por CDK CLI)

### Acceso AWS

- Cuenta AWS con permisos para crear: Lambda, Step Functions, DynamoDB, S3, EventBridge, SNS, CloudFront, IAM roles, CloudWatch
- Acceso al bucket de logs: `dev-logs-prompt-kiro-418295705477-us-east-1-an`
- Permisos de Bedrock para el modelo `us.anthropic.claude-haiku-4-5-20251001-v1:0`

---

## Instalación Local

```bash
# Clonar el repositorio
git clone <repo-url>
cd kiro-analytics

# Crear entorno virtual
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependencias (desarrollo + CDK)
pip install -e ".[dev,cdk]"
```

### Verificar instalación

```bash
# Ejecutar todos los tests (461+)
pytest

# Solo unitarios
pytest tests/unit/

# Solo Property-Based Tests
pytest tests/pbt/

# Solo integración
pytest tests/integration/
```

---

## Configuración para Producción

### 1. Configurar parámetros del stack

Editar `infrastructure/app.py` con los valores de producción:

```python
config = StackConfig(
    # Bucket donde están los logs de Kiro
    logs_bucket="dev-logs-prompt-kiro-418295705477-us-east-1-an",

    # Cuenta AWS de producción
    account_id="418295705477",
    region="us-east-1",

    # Correos para notificaciones (1-10 destinatarios)
    notification_emails=[
        "lider-tecnico@empresa.com",
        "gerente@empresa.com",
    ],

    # Correos autorizados para acceder al sitio de reportes
    authorized_emails=[
        "equipo-dev@empresa.com",
        "stakeholder@empresa.com",
    ],

    # Modelo de Bedrock (no cambiar sin verificar disponibilidad)
    bedrock_model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",

    # Runtime Python para Lambda
    python_runtime="python3.13",

    # Retención de logs (días)
    log_retention_days=30,

    # Retención de reportes (días) — ciclo de vida S3
    report_retention_days=90,
)
```

### 2. Preparar el roster de usuarios

El roster define qué usuarios se incluyen en los reportes. Formato CSV:

```csv
Username,Display name,Status,Email,User ID
jverbel,Juan Verbel,Enabled,jverbel@empresa.com,uuid-001
maria,Maria Garcia,Enabled,maria@empresa.com,uuid-002
inactivo,Usuario Inactivo,Disabled,inactivo@empresa.com,uuid-003
```

- Solo usuarios con `Status=Enabled` se procesan
- El archivo se lee desde S3 en cada ejecución (actualizable sin redespliegue)
- Ubicación por defecto: `s3://<reports-bucket>/config/kiro-users-dev.csv`

### 3. Habilitar acceso a Bedrock

Verificar que el modelo Claude Haiku 4.5 esté habilitado en la región:

```bash
aws bedrock list-foundation-models \
  --query "modelSummaries[?modelId=='anthropic.claude-haiku-4-5-20251001-v1:0']" \
  --region us-east-1
```

Si no aparece, habilitar desde la consola AWS → Bedrock → Model access.

---

## Despliegue en Producción

### Paso 1: Bootstrap del entorno CDK (solo la primera vez)

```bash
cdk bootstrap aws://418295705477/us-east-1
```

### Paso 2: Sintetizar el template (verificar sin desplegar)

```bash
PYTHONPATH=. cdk synth --app "python3 infrastructure/app.py"
```

Esto genera el template CloudFormation en `cdk.out/`. Revisarlo para verificar los recursos.

### Paso 3: Desplegar el stack

```bash
PYTHONPATH=. cdk deploy KiroAnalyticsPipeline --app "python3 infrastructure/app.py"
```

CDK mostrará los cambios propuestos y pedirá confirmación. Recursos creados:

- **DynamoDB**: `kiro-analytics-metrics` (on-demand, point-in-time recovery)
- **S3**: `kiro-analytics-reports-418295705477-us-east-1` (versionado, lifecycle 90 días)
- **Lambda**: 9 funciones (`kiro-analytics-*`)
- **Step Functions**: `KiroAnalyticsPipeline-*`
- **EventBridge**: 3 reglas (diario, semanal, mensual)
- **SNS**: `kiro-analytics-notifications`
- **CloudFront**: Distribución para sitio de reportes
- **CloudWatch**: Alarmas de rendimiento y fallos consecutivos

### Paso 4: Confirmar suscripciones SNS

Después del despliegue, cada destinatario recibirá un correo de confirmación de SNS. **Deben confirmar la suscripción** haciendo clic en el enlace del correo para empezar a recibir notificaciones.

### Paso 5: Subir el roster a S3

```bash
aws s3 cp kiro-users-dev.csv \
  s3://kiro-analytics-reports-418295705477-us-east-1/config/kiro-users-dev.csv
```

### Paso 6: Verificar con ejecución manual

```bash
# Ejecutar reporte diario
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:418295705477:stateMachine:kiro-analytics-pipeline \
  --input '{"period": "daily", "reference_date": "2026-06-03", "ai_analysis": true}'
```

Monitorear en la consola: Step Functions → Ejecuciones → verificar que todas las etapas completen en verde.

Verificar resultados:
```bash
# Debe mostrar HTML y CSV generados
aws s3 ls s3://kiro-analytics-reports-418295705477-us-east-1/reports/

# Debe mostrar reportes publicados + index.html
aws s3 ls s3://kiro-analytics-reports-418295705477-us-east-1/site/
```

---

## Programación Automática

Una vez desplegado, EventBridge ejecuta automáticamente:

| Schedule | Frecuencia | Hora (COT) | Período | Fecha de referencia |
|----------|-----------|------------|---------|---------------------|
| Semanal | Viernes | 7:00 AM | `weekly` | Lunes semana anterior |
| Mensual | Día 1 | 7:00 AM | `monthly` | 1er día mes anterior |

No requiere intervención manual. Los reportes se publican automáticamente en el sitio CloudFront y se envían notificaciones por correo.

---

## Ejecución Manual

### Vía AWS CLI

```bash
STATE_MACHINE_ARN="arn:aws:states:us-east-1:418295705477:stateMachine:kiro-analytics-pipeline"

# Reporte diario
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"period": "daily", "reference_date": "2026-06-03"}'

# Reporte semanal (la fecha de referencia es cualquier día de la semana deseada)
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"period": "weekly", "reference_date": "2026-06-02"}'

# Reporte mensual
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"period": "monthly", "reference_date": "2026-05-01"}'

# Sin análisis AI (más rápido, sin costo Bedrock)
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"period": "weekly", "reference_date": "2026-06-02", "ai_analysis": false}'

# Solo formato HTML
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"period": "daily", "reference_date": "2026-06-03", "output_format": "html"}'
```

**Nota:** Se requiere el permiso `states:StartExecution` sobre la state machine. El usuario CLI necesita una política inline con esta acción.

### Parámetros de entrada

| Parámetro | Tipo | Requerido | Valores | Default |
|-----------|------|-----------|---------|---------|
| `period` | string | ✅ | `daily`, `weekly`, `monthly` | — |
| `reference_date` | string | ✅ | Formato `YYYY-MM-DD` | — |
| `ai_analysis` | boolean | ❌ | `true`, `false` | `true` |
| `output_format` | string | ❌ | `html`, `csv`, `both` | `both` |

### Validación post-ejecución

Después de ejecutar, verificar los resultados:

```bash
# Verificar reportes generados
aws s3 ls s3://kiro-analytics-reports-418295705477-us-east-1/reports/

# Verificar publicación en sitio
aws s3 ls s3://kiro-analytics-reports-418295705477-us-east-1/site/
```

---

## Acceso al Sitio de Reportes

El sitio de reportes está protegido con autenticación HTTP Basic Auth.

- **URL:** https://d1yducpxutmfec.cloudfront.net
- **Usuario:** `kiroanalytics`
- **Contraseña:** `K1r0@n$lyt1cs`

El sitio incluye:
- Página índice con listado de todos los reportes por periodo
- Reportes HTML auto-contenidos con gráficos, tablas y análisis AI
- Los reportes también están disponibles vía URLs pre-firmadas S3 (validez 7 días)

---

## Monitoreo y Observabilidad

### CloudWatch Logs

Cada función Lambda emite logs estructurados. Buscar por grupos:

```bash
# Ver logs del pipeline
aws logs filter-log-events \
  --log-group-name /aws/lambda/kiro-analytics-procesador \
  --start-time $(date -d '1 hour ago' +%s000)
```

### Métricas personalizadas

El pipeline emite métricas a CloudWatch:
- **Duración total** (segundos)
- **Duración por etapa** (segundos)
- **Usuarios procesados** (count)
- **Tamaño de datos recolectados** (bytes)

### Alarmas configuradas

| Alarma | Condición | Severidad |
|--------|-----------|-----------|
| Rendimiento degradado | Duración > 5 minutos | Media |
| Fallos consecutivos | 3 fallos seguidos en ejecuciones programadas | Alta |

Las alarmas notifican al tópico SNS (mismos destinatarios del pipeline).

---

## Degradación Elegante

El pipeline está diseñado para producir resultados parciales:

| Componente que falla | Comportamiento | Reporte generado |
|---------------------|----------------|------------------|
| Bedrock (análisis AI) | Continúa sin AI | ✅ Sin sección de análisis AI |
| Publicación web | Continúa con indicador | ✅ Disponible vía URL pre-firmada |
| Notificación | Log en CloudWatch | ✅ Pipeline marca éxito |
| Recolección (1 fuente) | Fallo total del pipeline | ❌ No se genera reporte |

---

## Actualización del Roster

Para agregar/remover usuarios de los reportes, solo actualizar el CSV en S3:

```bash
# Editar localmente
vi kiro-users-dev.csv

# Subir nueva versión
aws s3 cp kiro-users-dev.csv \
  s3://kiro-analytics-reports-418295705477-us-east-1/config/kiro-users-dev.csv
```

La siguiente ejecución usará la versión actualizada automáticamente. No requiere redespliegue.

---

## Actualización del Stack

Para modificar configuración (emails, retención, modelo AI):

```bash
# Editar infrastructure/app.py con nuevos valores
# Luego redesplegar desde la raíz del proyecto:
PYTHONPATH=. cdk deploy KiroAnalyticsPipeline --app "python3 infrastructure/app.py"
```

CDK actualiza solo los recursos modificados sin perder datos en DynamoDB ni S3.

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
│   ├── analyzers/                # Análisis AI con Bedrock
│   ├── generators/               # Generación de reportes y publicación
│   ├── notifiers/                # Notificaciones por SNS
│   ├── orchestrator/             # Handler Lambda y orquestación
│   └── utils/                    # Utilidades compartidas
├── infrastructure/               # AWS CDK (IaC)
│   ├── app.py                    # Entry point CDK
│   ├── pipeline_stack.py         # Stack principal
│   └── state_machine.py         # Step Functions state machine
├── tests/                        # 461+ tests
│   ├── unit/                     # Tests unitarios
│   ├── pbt/                      # Property-Based Tests (Hypothesis)
│   └── integration/              # Tests de integración (moto)
├── kiro_usage_report.py          # Script legacy (referencia)
├── kiro-users-dev.csv            # Roster de ejemplo
└── pyproject.toml                # Configuración y dependencias
```

---

## Troubleshooting

### El pipeline falla en "lectura_roster"

- Verificar que el archivo CSV existe en S3: `aws s3 ls s3://<bucket>/config/kiro-users-dev.csv`
- Verificar formato: debe tener encabezado `Username,Display name,Status,Email,User ID` y al menos 1 fila de datos

### El pipeline falla en "recoleccion"

- Verificar que el bucket de logs existe y la Lambda tiene permisos de lectura
- Verificar que hay datos en las fechas solicitadas: `aws s3 ls s3://<logs-bucket>/kiro/ --recursive | grep 2026/06/07`

### No llegan notificaciones

- Verificar que los destinatarios confirmaron la suscripción SNS (revisar correo spam)
- Verificar en CloudWatch Logs del notificador si hay errores

### Análisis AI no disponible

- Verificar acceso al modelo Bedrock: `aws bedrock list-foundation-models --region us-east-1`
- El pipeline continúa y genera reporte sin la sección AI (degradación elegante)

### Timeout de ejecución (>10 min)

- Verificar tamaño de datos: muchos archivos en el periodo pueden causar lentitud
- Considerar ejecutar periodos más cortos o verificar si hay throttling de S3

---

## Costos Estimados (USD/mes)

| Servicio | Costo estimado | Notas |
|----------|---------------|-------|
| Lambda | ~$1-5 | 9 funciones, ~90 ejecuciones/mes |
| Step Functions | ~$0.50 | ~90 transiciones de estado/mes |
| DynamoDB | ~$1-3 | On-demand, ~3000 escrituras/mes |
| S3 | ~$0.50-2 | Almacenamiento de reportes + logs temporales |
| EventBridge | Gratis | Primeros 14M eventos incluidos |
| Bedrock | ~$5-20 | Depende del volumen de prompts analizados |
| CloudFront | ~$0.50-1 | Bajo tráfico (equipo interno) |
| SNS | ~$0.10 | ~90 correos/mes |
| CloudWatch | ~$1-3 | Logs + métricas + alarmas |
| **Total** | **~$10-35/mes** | Uso típico para equipo de 20-50 usuarios |

---

## Licencia

Uso interno — Solati.
