# Políticas IAM necesarias para your-iam-user

El usuario `your-iam-user` (cuenta 123456789012) actualmente tiene acceso a:
- ✅ S3, Lambda, Step Functions, CloudWatch (Logs/Metrics), Bedrock, CloudFormation, IAM (lectura)

Pero le faltan permisos para desplegar el proyecto completo.

## Políticas a crear

### 1. `kiro-analytics-cdk-bootstrap` — Permisos para CDK Bootstrap
Archivo: `kiro-analytics-cdk-bootstrap.json`

Otorga acceso a: ECR, SSM, KMS e IAM (scoped a recursos `cdk-hnb659fds-*`).

### 2. `kiro-analytics-pipeline-deploy` — Permisos para desplegar el pipeline
Archivo: `kiro-analytics-pipeline-deploy.json`

Otorga acceso a: DynamoDB, SNS, EventBridge, CloudFront, IAM (scoped a `kiro-analytics-*`), CloudWatch Alarms.

## Comandos para aplicar (requiere un administrador de la cuenta)

```bash
# Crear política de bootstrap
aws iam create-policy \
  --policy-name kiro-analytics-cdk-bootstrap \
  --policy-document file://infrastructure/iam-policies/kiro-analytics-cdk-bootstrap.json \
  --description "Permisos para CDK bootstrap del proyecto kiro-analytics"

# Crear política del pipeline
aws iam create-policy \
  --policy-name kiro-analytics-pipeline-deploy \
  --policy-document file://infrastructure/iam-policies/kiro-analytics-pipeline-deploy.json \
  --description "Permisos para desplegar el pipeline kiro-analytics"

# Adjuntar ambas al usuario your-iam-user
aws iam attach-user-policy \
  --user-name your-iam-user \
  --policy-arn arn:aws:iam::123456789012:policy/kiro-analytics-cdk-bootstrap

aws iam attach-user-policy \
  --user-name your-iam-user \
  --policy-arn arn:aws:iam::123456789012:policy/kiro-analytics-pipeline-deploy
```

## Después de aplicar las políticas

```bash
cd infrastructure

# 1. Bootstrap (solo una vez)
cdk bootstrap aws://123456789012/us-east-1

# 2. Desplegar
cdk deploy KiroAnalyticsPipeline
```
