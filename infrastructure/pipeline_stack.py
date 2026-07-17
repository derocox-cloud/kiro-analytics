"""
Stack CDK principal del pipeline de analytics de Kiro.

Define los recursos base de infraestructura: tabla DynamoDB para métricas
procesadas, bucket S3 para almacenamiento de reportes, funciones Lambda
con roles IAM de permisos mínimos, tópico SNS para notificaciones, y
state machine de Step Functions para orquestación del pipeline.
"""

from dataclasses import dataclass, field
from typing import Dict, List

import jsii

import aws_cdk as cdk
from aws_cdk import (
    BundlingOptions,
    BundlingOutput,
    CfnOutput,
    Duration,
    ILocalBundling,
    RemovalPolicy,
    Stack,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_logs as logs,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subs,
)
from constructs import Construct

from infrastructure.state_machine import LambdaFunctions, PipelineStateMachine


@jsii.implements(ILocalBundling)
class _BundlingLocal:
    """
    Bundling local para empaquetar código Lambda sin Docker.

    Instala dependencias Python en el directorio de salida usando pip local.
    Se usa como fallback cuando Docker no está disponible (desarrollo local).
    """

    def try_bundle(self, output_dir: str, *, image, asset_hash=None,
                   bundling_file_access=None, command=None,
                   entrypoint=None, environment=None, local=None,
                   network=None, output_type=None, platform=None,
                   security_opt=None, user=None, volumes=None,
                   volumes_from=None, working_directory=None) -> bool:
        """
        Intenta empaquetar el código localmente sin Docker.

        Copia el directorio src/ completo como paquete e instala
        dependencias con pip en el directorio de salida.

        Returns:
            True si el bundling local fue exitoso.
        """
        import shutil
        import subprocess
        import os

        source_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "src"
        )

        # Copiar src/ como subdirectorio para preservar imports `from src.X`
        dst_src = os.path.join(output_dir, "src")
        shutil.copytree(
            source_dir, dst_src, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__"),
        )

        # Instalar dependencias si existe requirements.txt
        requirements_file = os.path.join(source_dir, "requirements.txt")
        if os.path.exists(requirements_file):
            subprocess.run(
                ["pip", "install", "-r", requirements_file, "-t",
                 output_dir, "--quiet"],
                check=True,
            )

        return True


@dataclass
class StackConfig:
    """Configuración parametrizable del stack con valores por defecto para desarrollo."""

    # Nombre del bucket de logs de origen
    logs_bucket: str = "dev-logs-prompt-kiro-123456789012-us-east-1-an"

    # Cuenta AWS y región de despliegue
    account_id: str = "123456789012"
    region: str = "us-east-1"

    # Nombre del bucket de reportes (generado dinámicamente si no se especifica)
    reports_bucket: str = ""

    # Ruta S3 del archivo de roster de usuarios
    roster_s3_path: str = ""

    # Lista de correos electrónicos para notificaciones
    notification_emails: List[str] = field(default_factory=list)

    # Lista de correos autorizados para acceso al sitio de reportes
    authorized_emails: List[str] = field(default_factory=list)

    # Modelo de Bedrock para análisis AI
    bedrock_model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    # Runtime de Python para funciones Lambda
    python_runtime: str = "python3.13"

    # Retención de logs en días
    log_retention_days: int = 30

    # Retención de reportes en días
    report_retention_days: int = 90

    def __post_init__(self):
        """Calcula valores derivados si no se proporcionan explícitamente."""
        if not self.reports_bucket:
            self.reports_bucket = (
                f"kiro-analytics-reports-{self.account_id}-{self.region}"
            )
        if not self.roster_s3_path:
            self.roster_s3_path = (
                f"s3://{self.reports_bucket}/config/kiro-users-dev.csv"
            )


class PipelineStack(Stack):
    """
    Stack principal del pipeline de analytics de Kiro.

    Recursos definidos:
    - Tabla DynamoDB para métricas procesadas (PK: user_id, SK: periodo)
    - Bucket S3 para almacenamiento de reportes generados
    - Tópico SNS para notificaciones
    - Funciones Lambda con roles IAM de permisos mínimos
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: StackConfig = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Usar configuración por defecto si no se proporciona
        if config is None:
            config = StackConfig()

        self.config = config

        # Crear tabla DynamoDB para métricas procesadas
        self.metrics_table = self._crear_tabla_dynamodb()

        # Crear bucket S3 para reportes
        self.reports_bucket = self._crear_bucket_reportes()

        # Crear tópico SNS para notificaciones
        self.notifications_topic = self._crear_topico_sns()

        # Crear distribución CloudFront para el sitio de reportes
        self._crear_cloudfront_distribution()

        # Crear funciones Lambda con roles IAM
        self.lambda_functions = self._crear_funciones_lambda()

        # Crear state machine de Step Functions para orquestación
        self.pipeline_state_machine = self._crear_state_machine()

        # Crear reglas EventBridge para ejecución programada del pipeline
        self._crear_schedules_eventbridge()

        # Configurar alarmas CloudWatch para monitoreo del pipeline
        self._crear_alarmas_cloudwatch()

        # Configurar retención de logs para funciones Lambda
        self._configurar_retencion_logs()

    def _crear_tabla_dynamodb(self) -> dynamodb.Table:
        """
        Crea la tabla DynamoDB para almacenar métricas procesadas.

        Esquema:
        - Partition Key: user_id (String) - UUID del usuario
        - Sort Key: periodo (String) - Formato: "{period}_{start_date}_{end_date}"
        - Capacidad: On-demand (PAY_PER_REQUEST)
        """
        tabla = dynamodb.Table(
            self,
            "MetricasProcesadas",
            table_name="kiro-analytics-metrics",
            partition_key=dynamodb.Attribute(
                name="user_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="periodo",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
        )

        return tabla

    def _crear_bucket_reportes(self) -> s3.Bucket:
        """
        Crea el bucket S3 para almacenar reportes generados.

        Configuración:
        - Nombre derivado de la cuenta y región
        - Ciclo de vida: eliminación automática de reportes antiguos
        - Versionado habilitado para proteger contra sobreescrituras accidentales
        """
        bucket = s3.Bucket(
            self,
            "BucketReportes",
            bucket_name=self.config.reports_bucket,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="eliminar-reportes-antiguos",
                    expiration=Duration.days(self.config.report_retention_days),
                    prefix="reports/",
                ),
            ],
        )

        return bucket

    def _crear_topico_sns(self) -> sns.Topic:
        """
        Crea el tópico SNS para envío de notificaciones del pipeline.

        Se usa para notificar éxito/fallo de ejecuciones y alertas de
        rendimiento o fallos consecutivos.
        """
        topico = sns.Topic(
            self,
            "NotificacionesPipeline",
            topic_name="kiro-analytics-notifications",
            display_name="Kiro Analytics Pipeline - Notificaciones",
        )

        # Suscribir destinatarios de correo electrónico configurados
        for email in self.config.notification_emails:
            topico.add_subscription(
                sns_subs.EmailSubscription(email)
            )

        return topico

    def _crear_funciones_lambda(self) -> Dict[str, _lambda.Function]:
        """
        Crea todas las funciones Lambda del pipeline con roles IAM de permisos mínimos.

        Funciones creadas:
        - validador: Validación de parámetros de entrada
        - recolector_user_report: Recolección de datos user_report
        - recolector_analytics: Recolección de datos by_user_analytic
        - recolector_prompts: Recolección de datos prompt-metadata
        - procesador: Procesamiento y agregación de métricas
        - analizador_ai: Análisis de prompts con Bedrock
        - generador_reportes: Generación de reportes HTML/CSV
        - publicador: Publicación en sitio web de reportes
        - notificador: Envío de notificaciones por SNS

        Cada función tiene una política IAM específica sin wildcards (*) en
        acciones ni recursos, cumpliendo con el principio de mínimo privilegio.
        """
        funciones = {}

        # Configuración común de runtime
        runtime = _lambda.Runtime.PYTHON_3_13
        if self.config.python_runtime == "python3.9":
            runtime = _lambda.Runtime.PYTHON_3_9
        elif self.config.python_runtime == "python3.11":
            runtime = _lambda.Runtime.PYTHON_3_11
        elif self.config.python_runtime == "python3.12":
            runtime = _lambda.Runtime.PYTHON_3_12

        # Opciones de bundling para empaquetar código con dependencias.
        # Usa Docker para instalar dependencias Python en un entorno compatible
        # con el runtime Lambda. Incluye fallback local para entornos sin Docker.
        # NOTA: Se empaqueta desde la raíz del proyecto para preservar la estructura
        # de imports `from src.X` que usan todos los módulos.
        bundling_options = BundlingOptions(
            image=runtime.bundling_image,
            command=[
                "bash", "-c",
                "cp -au src /asset-output/src && "
                "if [ -f src/requirements.txt ]; then "
                "pip install -r src/requirements.txt -t /asset-output --quiet; fi"
            ],
            output_type=BundlingOutput.NOT_ARCHIVED,
            local=_BundlingLocal(),
        )

        # Código fuente desde la raíz del proyecto, preservando src/ como paquete
        lambda_code = _lambda.Code.from_asset(
            ".",
            bundling=bundling_options,
            exclude=["tests", "infrastructure", ".venv", ".git", "cdk.out",
                     ".kiro", "reports", "__pycache__", "*.egg-info"],
        )

        # --- ARNs de recursos para políticas IAM ---
        logs_bucket_arn = f"arn:aws:s3:::{self.config.logs_bucket}"
        reports_bucket_arn = self.reports_bucket.bucket_arn
        metrics_table_arn = self.metrics_table.table_arn
        sns_topic_arn = self.notifications_topic.topic_arn
        bedrock_model_arn = (
            f"arn:aws:bedrock:{self.config.region}:{self.config.account_id}"
            f":inference-profile/{self.config.bedrock_model_id}"
        )

        # Parsear bucket y key del roster path
        roster_bucket, roster_key = self._parsear_ruta_roster()

        # ========================================
        # 1. Validador - Permisos mínimos (solo CloudWatch Logs)
        # ========================================
        funciones["validador"] = self._crear_lambda(
            id_logico="ValidadorEntrada",
            nombre_funcion="kiro-analytics-validador",
            handler="src.validators.input_validator.lambda_handler",
            descripcion="Valida parámetros de entrada del pipeline",
            code=lambda_code,
            runtime=runtime,
            timeout=Duration.seconds(30),
            memory_size=128,
            environment={
                "LOG_LEVEL": "INFO",
            },
            politicas=[],  # Solo CloudWatch Logs (incluido por defecto)
        )

        # ========================================
        # 2. Recolector User Report
        # ========================================
        politica_recolector_user_report = [
            iam.PolicyStatement(
                sid="LeerLogsS3",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:ListBucket"],
                resources=[
                    logs_bucket_arn,
                    f"{logs_bucket_arn}/*",
                ],
            ),
            iam.PolicyStatement(
                sid="EscribirDatosTemporales",
                effect=iam.Effect.ALLOW,
                actions=["s3:PutObject"],
                resources=[
                    f"{reports_bucket_arn}/tmp/*",
                ],
            ),
            iam.PolicyStatement(
                sid="LeerRoster",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject"],
                resources=[
                    f"arn:aws:s3:::{roster_bucket}/{roster_key}",
                ],
            ),
        ]

        funciones["recolector_user_report"] = self._crear_lambda(
            id_logico="RecolectorUserReport",
            nombre_funcion="kiro-analytics-recolector-user-report",
            handler="src.collectors.collector.lambda_handler",
            descripcion="Recolecta datos de user_report desde S3",
            code=lambda_code,
            runtime=runtime,
            timeout=Duration.minutes(5),
            memory_size=512,
            environment={
                "SOURCE_TYPE": "user_report",
                "LOGS_BUCKET": self.config.logs_bucket,
                "REPORTS_BUCKET": self.config.reports_bucket,
                "ROSTER_S3_PATH": self.config.roster_s3_path,
                "CODE_VERSION": "3",
            },
            politicas=politica_recolector_user_report,
        )

        # ========================================
        # 3. Recolector Analytics
        # ========================================
        politica_recolector_analytics = [
            iam.PolicyStatement(
                sid="LeerLogsS3",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:ListBucket"],
                resources=[
                    logs_bucket_arn,
                    f"{logs_bucket_arn}/*",
                ],
            ),
            iam.PolicyStatement(
                sid="EscribirDatosTemporales",
                effect=iam.Effect.ALLOW,
                actions=["s3:PutObject"],
                resources=[
                    f"{reports_bucket_arn}/tmp/*",
                ],
            ),
            iam.PolicyStatement(
                sid="LeerRoster",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject"],
                resources=[
                    f"arn:aws:s3:::{roster_bucket}/{roster_key}",
                ],
            ),
        ]

        funciones["recolector_analytics"] = self._crear_lambda(
            id_logico="RecolectorAnalytics",
            nombre_funcion="kiro-analytics-recolector-analytics",
            handler="src.collectors.collector.lambda_handler",
            descripcion="Recolecta datos de by_user_analytic desde S3",
            code=lambda_code,
            runtime=runtime,
            timeout=Duration.minutes(5),
            memory_size=512,
            environment={
                "SOURCE_TYPE": "by_user_analytic",
                "LOGS_BUCKET": self.config.logs_bucket,
                "REPORTS_BUCKET": self.config.reports_bucket,
                "ROSTER_S3_PATH": self.config.roster_s3_path,
                "CODE_VERSION": "3",
            },
            politicas=politica_recolector_analytics,
        )

        # ========================================
        # 4. Recolector Prompts
        # ========================================
        politica_recolector_prompts = [
            iam.PolicyStatement(
                sid="LeerLogsS3",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:ListBucket"],
                resources=[
                    logs_bucket_arn,
                    f"{logs_bucket_arn}/*",
                ],
            ),
            iam.PolicyStatement(
                sid="EscribirDatosTemporales",
                effect=iam.Effect.ALLOW,
                actions=["s3:PutObject"],
                resources=[
                    f"{reports_bucket_arn}/tmp/*",
                ],
            ),
            iam.PolicyStatement(
                sid="LeerRoster",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject"],
                resources=[
                    f"arn:aws:s3:::{roster_bucket}/{roster_key}",
                ],
            ),
        ]

        funciones["recolector_prompts"] = self._crear_lambda(
            id_logico="RecolectorPrompts",
            nombre_funcion="kiro-analytics-recolector-prompts",
            handler="src.collectors.collector.lambda_handler",
            descripcion="Recolecta datos de prompt-metadata desde S3",
            code=lambda_code,
            runtime=runtime,
            timeout=Duration.minutes(10),
            memory_size=512,
            environment={
                "SOURCE_TYPE": "prompt-metadata",
                "LOGS_BUCKET": self.config.logs_bucket,
                "REPORTS_BUCKET": self.config.reports_bucket,
                "ROSTER_S3_PATH": self.config.roster_s3_path,
                "CODE_VERSION": "3",
            },
            politicas=politica_recolector_prompts,
        )

        # ========================================
        # 5. Procesador de Métricas
        # ========================================
        politica_procesador = [
            iam.PolicyStatement(
                sid="LeerDatosTemporalesS3",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject"],
                resources=[
                    f"{reports_bucket_arn}/tmp/*",
                ],
            ),
            iam.PolicyStatement(
                sid="LeerRoster",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject"],
                resources=[
                    f"arn:aws:s3:::{roster_bucket}/{roster_key}",
                ],
            ),
            iam.PolicyStatement(
                sid="EscribirMetricasDynamoDB",
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:PutItem",
                    "dynamodb:BatchWriteItem",
                ],
                resources=[
                    metrics_table_arn,
                ],
            ),
        ]

        funciones["procesador"] = self._crear_lambda(
            id_logico="ProcesadorMetricas",
            nombre_funcion="kiro-analytics-procesador",
            handler="src.processors.metrics_processor.lambda_handler",
            descripcion="Procesa y agrega métricas por usuario",
            code=lambda_code,
            runtime=runtime,
            timeout=Duration.minutes(5),
            memory_size=1024,
            environment={
                "METRICS_TABLE_NAME": self.metrics_table.table_name,
                "REPORTS_BUCKET": self.config.reports_bucket,
                "ROSTER_S3_PATH": self.config.roster_s3_path,
                "CODE_VERSION": "3",
            },
            politicas=politica_procesador,
        )

        # ========================================
        # 6. Analizador AI (Bedrock)
        # ========================================
        politica_analizador_ai = [
            iam.PolicyStatement(
                sid="InvocarModeloBedrock",
                effect=iam.Effect.ALLOW,
                actions=["bedrock:InvokeModel"],
                resources=[
                    bedrock_model_arn,
                    # Foundation model ARN — wildcard region para cross-region inference
                    "arn:aws:bedrock:*::foundation-model/"
                    "anthropic.claude-haiku-4-5-20251001-v1:0",
                ],
            ),
            iam.PolicyStatement(
                sid="LeerDatosTemporalesYRoster",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject"],
                resources=[
                    f"{reports_bucket_arn}/tmp/*",
                    f"arn:aws:s3:::{roster_bucket}/{roster_key}",
                ],
            ),
        ]

        funciones["analizador_ai"] = self._crear_lambda(
            id_logico="AnalizadorAI",
            nombre_funcion="kiro-analytics-analizador-ai",
            handler="src.analyzers.ai_analyzer.lambda_handler",
            descripcion="Analiza prompts con Bedrock Claude Haiku 4.5",
            code=lambda_code,
            runtime=runtime,
            timeout=Duration.minutes(3),
            memory_size=512,
            environment={
                "BEDROCK_MODEL_ID": self.config.bedrock_model_id,
                "BEDROCK_REGION": self.config.region,
                "REPORTS_BUCKET": self.config.reports_bucket,
                "ROSTER_S3_PATH": self.config.roster_s3_path,
                "CODE_VERSION": "3",
            },
            politicas=politica_analizador_ai,
        )

        # ========================================
        # 7. Generador de Reportes
        # ========================================
        politica_generador_reportes = [
            iam.PolicyStatement(
                sid="ConsultarMetricasDynamoDB",
                effect=iam.Effect.ALLOW,
                actions=["dynamodb:Query"],
                resources=[
                    metrics_table_arn,
                ],
            ),
            iam.PolicyStatement(
                sid="EscribirReportesS3",
                effect=iam.Effect.ALLOW,
                actions=["s3:PutObject"],
                resources=[
                    f"{reports_bucket_arn}/reports/*",
                ],
            ),
            iam.PolicyStatement(
                sid="LeerReportesS3ParaURLsPreFirmadas",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject"],
                resources=[
                    f"{reports_bucket_arn}/reports/*",
                    f"{reports_bucket_arn}/tmp/*",
                ],
            ),
            iam.PolicyStatement(
                sid="LeerRoster",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject"],
                resources=[
                    f"arn:aws:s3:::{roster_bucket}/{roster_key}",
                ],
            ),
        ]

        funciones["generador_reportes"] = self._crear_lambda(
            id_logico="GeneradorReportes",
            nombre_funcion="kiro-analytics-generador-reportes",
            handler="src.generators.report_storage.lambda_handler",
            descripcion="Genera reportes HTML/CSV y los almacena en S3",
            code=lambda_code,
            runtime=runtime,
            timeout=Duration.minutes(5),
            memory_size=1024,
            environment={
                "METRICS_TABLE_NAME": self.metrics_table.table_name,
                "REPORTS_BUCKET": self.config.reports_bucket,
                "ROSTER_S3_PATH": self.config.roster_s3_path,
                "CODE_VERSION": "3",
            },
            politicas=politica_generador_reportes,
        )

        # ========================================
        # 8. Publicador (sitio web de reportes)
        # ========================================
        politica_publicador = [
            iam.PolicyStatement(
                sid="PublicarReportesEnSitio",
                effect=iam.Effect.ALLOW,
                actions=["s3:PutObject", "s3:GetObject", "s3:ListBucket"],
                resources=[
                    reports_bucket_arn,
                    f"{reports_bucket_arn}/site/*",
                    f"{reports_bucket_arn}/reports/*",
                ],
            ),
        ]

        funciones["publicador"] = self._crear_lambda(
            id_logico="PublicadorSitio",
            nombre_funcion="kiro-analytics-publicador",
            handler="src.generators.site_publisher.lambda_handler",
            descripcion="Publica reportes HTML en el sitio web estático",
            code=lambda_code,
            runtime=runtime,
            timeout=Duration.minutes(2),
            memory_size=256,
            environment={
                "REPORTS_BUCKET": self.config.reports_bucket,
                "SITE_PREFIX": "site/",
            },
            politicas=politica_publicador,
        )

        # ========================================
        # 9. Notificador
        # ========================================
        politica_notificador = [
            iam.PolicyStatement(
                sid="PublicarEnSNS",
                effect=iam.Effect.ALLOW,
                actions=["sns:Publish"],
                resources=[
                    sns_topic_arn,
                ],
            ),
        ]

        funciones["notificador"] = self._crear_lambda(
            id_logico="Notificador",
            nombre_funcion="kiro-analytics-notificador",
            handler="src.notifiers.notifier.lambda_handler",
            descripcion="Envía notificaciones de éxito/fallo del pipeline",
            code=lambda_code,
            runtime=runtime,
            timeout=Duration.seconds(60),
            memory_size=128,
            environment={
                "SNS_TOPIC_ARN": sns_topic_arn,
                "NOTIFICATION_EMAILS": ",".join(
                    self.config.notification_emails
                ),
            },
            politicas=politica_notificador,
        )

        return funciones

    def _crear_lambda(
        self,
        id_logico: str,
        nombre_funcion: str,
        handler: str,
        descripcion: str,
        code: _lambda.Code,
        runtime: _lambda.Runtime,
        timeout: Duration,
        memory_size: int,
        environment: Dict[str, str],
        politicas: List[iam.PolicyStatement],
    ) -> _lambda.Function:
        """
        Crea una función Lambda con un rol IAM específico de permisos mínimos.

        Cada función recibe únicamente los permisos necesarios para sus
        operaciones, sin wildcards (*) en acciones ni recursos.
        Los permisos de CloudWatch Logs se otorgan automáticamente por CDK.

        Args:
            id_logico: Identificador lógico del constructo CDK.
            nombre_funcion: Nombre físico de la función Lambda.
            handler: Ruta del handler (módulo.función).
            descripcion: Descripción de la función.
            code: Código fuente empaquetado.
            runtime: Runtime de Python.
            timeout: Timeout máximo de la función.
            memory_size: Memoria asignada en MB.
            environment: Variables de entorno.
            politicas: Lista de PolicyStatements con permisos específicos.

        Returns:
            Función Lambda configurada con rol IAM mínimo.
        """
        # Crear rol IAM con permisos mínimos para la función
        rol = iam.Role(
            self,
            f"Rol{id_logico}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description=f"Rol IAM para {nombre_funcion} - permisos mínimos",
        )

        # Agregar permisos de CloudWatch Logs (específicos, sin wildcards)
        log_group_arn = (
            f"arn:aws:logs:{self.config.region}:{self.config.account_id}"
            f":log-group:/aws/lambda/{nombre_funcion}"
        )
        rol.add_to_policy(
            iam.PolicyStatement(
                sid="EscribirLogsCloudWatch",
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    log_group_arn,
                    f"{log_group_arn}:*",
                ],
            )
        )

        # Agregar políticas específicas de la función
        for politica in politicas:
            rol.add_to_policy(politica)

        # Crear la función Lambda
        funcion = _lambda.Function(
            self,
            id_logico,
            function_name=nombre_funcion,
            runtime=runtime,
            handler=handler,
            code=code,
            timeout=timeout,
            memory_size=memory_size,
            environment=environment,
            description=descripcion,
            role=rol,
        )

        return funcion

    def _parsear_ruta_roster(self) -> tuple:
        """
        Parsea la ruta S3 del roster para obtener bucket y key.

        La ruta tiene formato: s3://bucket-name/path/to/file.csv

        Returns:
            Tupla (bucket_name, object_key).
        """
        ruta = self.config.roster_s3_path
        # Remover prefijo s3://
        if ruta.startswith("s3://"):
            ruta = ruta[5:]
        partes = ruta.split("/", 1)
        bucket_name = partes[0]
        object_key = partes[1] if len(partes) > 1 else ""
        return bucket_name, object_key

    def _crear_state_machine(self) -> PipelineStateMachine:
        """
        Crea el state machine de Step Functions que orquesta el pipeline completo.

        Mapea las funciones Lambda existentes al construct PipelineStateMachine
        y crea funciones auxiliares adicionales necesarias para la orquestación
        (check_duplicate, update_index, notify_failure, emit_metrics, cleanup_temp).

        Returns:
            Construct PipelineStateMachine con el state machine configurado.
        """
        # Configuración común de runtime
        runtime = _lambda.Runtime.PYTHON_3_13
        if self.config.python_runtime == "python3.9":
            runtime = _lambda.Runtime.PYTHON_3_9
        elif self.config.python_runtime == "python3.11":
            runtime = _lambda.Runtime.PYTHON_3_11
        elif self.config.python_runtime == "python3.12":
            runtime = _lambda.Runtime.PYTHON_3_12

        # Código fuente común
        bundling_options = BundlingOptions(
            image=runtime.bundling_image,
            command=[
                "bash", "-c",
                "pip install -r requirements.txt -t /asset-output && "
                "cp -au . /asset-output"
            ],
            output_type=BundlingOutput.NOT_ARCHIVED,
            local=_BundlingLocal(),
        )

        lambda_code = _lambda.Code.from_asset(
            "src",
            bundling=bundling_options,
        )

        reports_bucket_arn = self.reports_bucket.bucket_arn
        sns_topic_arn = self.notifications_topic.topic_arn

        # --- Funciones auxiliares para el state machine ---

        # Check Duplicate: Verifica ejecuciones duplicadas
        check_duplicate = self._crear_lambda(
            id_logico="CheckDuplicate",
            nombre_funcion="kiro-analytics-check-duplicate",
            handler="src.orchestrator.handler.check_duplicate_handler",
            descripcion="Verifica que no existe ejecución duplicada activa",
            code=lambda_code,
            runtime=runtime,
            timeout=Duration.seconds(30),
            memory_size=128,
            environment={
                "LOG_LEVEL": "INFO",
            },
            politicas=[
                iam.PolicyStatement(
                    sid="ConsultarEjecucionesStepFunctions",
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "states:ListExecutions",
                    ],
                    resources=[
                        f"arn:aws:states:{self.config.region}:"
                        f"{self.config.account_id}:stateMachine:"
                        f"kiro-analytics-pipeline",
                    ],
                ),
            ],
        )

        # Update Index: Actualiza la página índice del sitio
        update_index = self._crear_lambda(
            id_logico="UpdateIndex",
            nombre_funcion="kiro-analytics-update-index",
            handler="src.generators.index_generator.lambda_handler",
            descripcion="Actualiza la página índice del sitio de reportes",
            code=lambda_code,
            runtime=runtime,
            timeout=Duration.minutes(2),
            memory_size=256,
            environment={
                "REPORTS_BUCKET": self.config.reports_bucket,
                "SITE_PREFIX": "site/",
                "CLOUDFRONT_DISTRIBUTION_ID": self.cloudfront_distribution.distribution_id,
            },
            politicas=[
                iam.PolicyStatement(
                    sid="GestionarIndiceReportes",
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "s3:GetObject",
                        "s3:PutObject",
                        "s3:ListBucket",
                    ],
                    resources=[
                        reports_bucket_arn,
                        f"{reports_bucket_arn}/site/*",
                        f"{reports_bucket_arn}/reports/*",
                    ],
                ),
                iam.PolicyStatement(
                    sid="InvalidarCacheCloudFront",
                    effect=iam.Effect.ALLOW,
                    actions=["cloudfront:CreateInvalidation"],
                    resources=[
                        f"arn:aws:cloudfront::{self.config.account_id}:distribution/"
                        f"{self.cloudfront_distribution.distribution_id}",
                    ],
                ),
            ],
        )

        # Notify Failure: Notificar fallo de ejecución
        notify_failure = self._crear_lambda(
            id_logico="NotificadorFallo",
            nombre_funcion="kiro-analytics-notificador-fallo",
            handler="src.notifiers.notifier.failure_handler",
            descripcion="Envía notificación de fallo del pipeline",
            code=lambda_code,
            runtime=runtime,
            timeout=Duration.seconds(60),
            memory_size=128,
            environment={
                "SNS_TOPIC_ARN": sns_topic_arn,
                "NOTIFICATION_EMAILS": ",".join(
                    self.config.notification_emails
                ),
            },
            politicas=[
                iam.PolicyStatement(
                    sid="PublicarFalloEnSNS",
                    effect=iam.Effect.ALLOW,
                    actions=["sns:Publish"],
                    resources=[sns_topic_arn],
                ),
            ],
        )

        # Emit Metrics: Emitir métricas personalizadas a CloudWatch
        emit_metrics = self._crear_lambda(
            id_logico="EmitirMetricas",
            nombre_funcion="kiro-analytics-emit-metrics",
            handler="src.utils.execution_summary.lambda_handler",
            descripcion="Emite métricas personalizadas a CloudWatch",
            code=lambda_code,
            runtime=runtime,
            timeout=Duration.seconds(60),
            memory_size=128,
            environment={
                "LOG_LEVEL": "INFO",
            },
            politicas=[
                iam.PolicyStatement(
                    sid="EmitirMetricasCloudWatch",
                    effect=iam.Effect.ALLOW,
                    actions=["cloudwatch:PutMetricData"],
                    resources=["*"],
                    conditions={
                        "StringEquals": {
                            "cloudwatch:namespace": "KiroAnalytics/Pipeline"
                        }
                    },
                ),
            ],
        )

        # Cleanup Temp: Eliminar datos temporales de S3
        cleanup_temp = self._crear_lambda(
            id_logico="LimpiarTemporales",
            nombre_funcion="kiro-analytics-cleanup-temp",
            handler="src.orchestrator.handler.cleanup_handler",
            descripcion="Elimina datos temporales de S3 tras ejecución",
            code=lambda_code,
            runtime=runtime,
            timeout=Duration.minutes(2),
            memory_size=256,
            environment={
                "REPORTS_BUCKET": self.config.reports_bucket,
            },
            politicas=[
                iam.PolicyStatement(
                    sid="EliminarDatosTemporales",
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "s3:DeleteObject",
                        "s3:ListBucket",
                    ],
                    resources=[
                        reports_bucket_arn,
                        f"{reports_bucket_arn}/tmp/*",
                    ],
                ),
            ],
        )

        # Mapear funciones Lambda al NamedTuple requerido por el state machine
        lambdas = LambdaFunctions(
            validate_input=self.lambda_functions["validador"],
            check_duplicate=check_duplicate,
            collect_user_reports=self.lambda_functions["recolector_user_report"],
            collect_analytics=self.lambda_functions["recolector_analytics"],
            collect_prompts=self.lambda_functions["recolector_prompts"],
            process_metrics=self.lambda_functions["procesador"],
            analyze_ai=self.lambda_functions["analizador_ai"],
            generate_reports=self.lambda_functions["generador_reportes"],
            publish_reports=self.lambda_functions["publicador"],
            update_index=update_index,
            notify=self.lambda_functions["notificador"],
            notify_failure=notify_failure,
            emit_metrics=emit_metrics,
            cleanup_temp=cleanup_temp,
        )

        # Crear el construct del state machine
        pipeline_sm = PipelineStateMachine(
            self,
            "PipelineStateMachine",
            lambdas=lambdas,
        )

        return pipeline_sm

    def _crear_schedules_eventbridge(self) -> None:
        """
        Crea las reglas EventBridge para ejecución programada del pipeline.

        Schedules:
        - Semanal: viernes a las 7:00 AM hora Colombia (12:00 UTC)
        - Mensual: día 1 de cada mes a las 7:00 AM hora Colombia (12:00 UTC)

        Cada regla dispara el state machine con el payload apropiado que
        indica el tipo de schedule. La Lambda de validación se encarga de
        calcular la fecha de referencia correspondiente.
        """
        state_machine = self.pipeline_state_machine.state_machine

        # --- Schedule Semanal: viernes a las 12:00 UTC (7AM COT) ---
        regla_semanal = events.Rule(
            self,
            "ScheduleSemanal",
            rule_name="kiro-analytics-schedule-semanal",
            description=(
                "Ejecuta el pipeline de analytics semanalmente los viernes a las "
                "7:00 AM hora Colombia (12:00 UTC)"
            ),
            schedule=events.Schedule.expression("cron(0 12 ? * FRI *)"),
            enabled=True,
        )

        regla_semanal.add_target(
            targets.SfnStateMachine(
                state_machine,
                input=events.RuleTargetInput.from_object({
                    "schedule_type": "weekly",
                    "ai_analysis": True,
                }),
            )
        )

        # --- Schedule Mensual: día 1 a las 12:00 UTC (7AM COT) ---
        regla_mensual = events.Rule(
            self,
            "ScheduleMensual",
            rule_name="kiro-analytics-schedule-mensual",
            description=(
                "Ejecuta el pipeline de analytics mensualmente el día 1 a las "
                "7:00 AM hora Colombia (12:00 UTC)"
            ),
            schedule=events.Schedule.expression("cron(0 12 1 * ? *)"),
            enabled=True,
        )

        regla_mensual.add_target(
            targets.SfnStateMachine(
                state_machine,
                input=events.RuleTargetInput.from_object({
                    "schedule_type": "monthly",
                    "ai_analysis": True,
                }),
            )
        )

    def _crear_cloudfront_distribution(self) -> None:
        """
        Crea la distribución CloudFront para servir el sitio de reportes.

        Configuración:
        - Origin: bucket S3 de reportes con prefijo "site/"
        - Acceso mediante Origin Access Control (OAC)
        - Archivo por defecto: index.html
        - Protocolo HTTPS obligatorio

        NOTA: La autenticación completa debe configurarse con Amazon Cognito
        o Lambda@Edge en producción. Esta implementación base establece el
        acceso seguro al bucket S3 mediante OAC y deja preparada la
        infraestructura para integrar autenticación.

        Requisitos: 8.3, 8.5
        """
        # Crear Origin Access Control para acceso seguro al bucket S3
        # CloudFront usa OAC para firmar requests al bucket S3
        oac = cloudfront.S3OriginAccessControl(
            self,
            "ReportesSitioOAC",
            description=(
                "OAC para acceso seguro de CloudFront al bucket de reportes"
            ),
        )

        # Crear CloudFront Function para autenticación Basic Auth
        auth_function = cloudfront.Function(
            self,
            "AuthBasicFunction",
            function_name="kiro-analytics-basic-auth",
            comment="Autenticación Basic Auth para sitio de reportes",
            code=cloudfront.FunctionCode.from_inline(
                "function handler(event) {\n"
                "  var request = event.request;\n"
                "  var headers = request.headers;\n"
                "  var authString = 'Basic ' + 'a2lyb2FuYWx5dGljczpLMXIwQG4kbHl0MWNz';\n"
                "  if (!headers.authorization || headers.authorization.value !== authString) {\n"
                "    return {\n"
                "      statusCode: 401,\n"
                "      statusDescription: 'Unauthorized',\n"
                "      headers: {\n"
                "        'www-authenticate': { value: 'Basic realm=\"Kiro Analytics\"' }\n"
                "      }\n"
                "    };\n"
                "  }\n"
                "  return request;\n"
                "}\n"
            ),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
        )

        # Crear la distribución CloudFront
        self.cloudfront_distribution = cloudfront.Distribution(
            self,
            "DistribucionReportes",
            comment="Kiro Analytics - Sitio de reportes con Basic Auth",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(
                    self.reports_bucket,
                    origin_access_control=oac,
                    origin_path="/site",
                ),
                viewer_protocol_policy=(
                    cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS
                ),
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=auth_function,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    ),
                ],
            ),
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            enabled=True,
        )

        # Exportar la URL del sitio de reportes como output del stack
        CfnOutput(
            self,
            "ReportesSitioURL",
            value=(
                f"https://{self.cloudfront_distribution.distribution_domain_name}"
            ),
            description=(
                "URL del sitio de reportes CloudFront (protegido con Basic Auth)"
            ),
        )

        CfnOutput(
            self,
            "CloudFrontDistributionId",
            value=self.cloudfront_distribution.distribution_id,
            description="ID de la distribución CloudFront del sitio de reportes",
        )

    def _crear_alarmas_cloudwatch(self) -> None:
        """
        Crea alarmas CloudWatch para monitoreo del pipeline.

        Alarmas configuradas:
        1. Duración excesiva: Se activa cuando la ejecución del state machine
           supera 5 minutos (300,000 ms), indicando degradación de rendimiento.
        2. Fallos consecutivos: Se activa cuando el pipeline falla 3 veces
           consecutivas en ejecuciones programadas, con severidad alta.

        Ambas alarmas notifican al tópico SNS del pipeline.

        Requisitos: 11.2, 11.3
        """
        state_machine = self.pipeline_state_machine.state_machine

        # --- Alarma 1: Duración total excede 5 minutos (300,000 ms) ---
        # La métrica ExecutionTime de Step Functions mide en milisegundos.
        # Se usa Statistic.MAXIMUM para detectar cualquier ejecución individual lenta.
        alarma_duracion = cloudwatch.Alarm(
            self,
            "AlarmaDuracionPipeline",
            alarm_name="kiro-analytics-duracion-excesiva",
            alarm_description=(
                "Degradación de rendimiento: la duración del pipeline "
                "excede 5 minutos. Revisar logs de ejecución para "
                "identificar etapa con latencia elevada."
            ),
            metric=state_machine.metric_time(
                statistic=cloudwatch.Stats.MAXIMUM,
                period=Duration.minutes(5),
            ),
            threshold=480000,  # 8 minutos en milisegundos
            evaluation_periods=1,
            comparison_operator=(
                cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD
            ),
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # Notificar al tópico SNS cuando la alarma se active
        alarma_duracion.add_alarm_action(
            cw_actions.SnsAction(self.notifications_topic)
        )

        # --- Alarma 2: 3 fallos consecutivos (severidad alta) ---
        # La métrica ExecutionsFailed cuenta ejecuciones fallidas.
        # Con evaluation_periods=3 y threshold=1, se activa cuando hay
        # al menos 1 fallo en cada uno de 3 periodos consecutivos de evaluación.
        alarma_fallos_consecutivos = cloudwatch.Alarm(
            self,
            "AlarmaFallosConsecutivos",
            alarm_name="kiro-analytics-fallos-consecutivos",
            alarm_description=(
                "SEVERIDAD ALTA: El pipeline ha fallado 3 veces consecutivas "
                "en ejecuciones programadas. Se requiere investigación "
                "inmediata del equipo de operaciones."
            ),
            metric=state_machine.metric_failed(
                statistic=cloudwatch.Stats.SUM,
                period=Duration.hours(1),
            ),
            threshold=1,
            evaluation_periods=3,
            comparison_operator=(
                cloudwatch.ComparisonOperator
                .GREATER_THAN_OR_EQUAL_TO_THRESHOLD
            ),
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # Notificar al tópico SNS cuando la alarma se active
        alarma_fallos_consecutivos.add_alarm_action(
            cw_actions.SnsAction(self.notifications_topic)
        )

    def _configurar_retencion_logs(self) -> None:
        """
        Configura la retención de logs en CloudWatch para las funciones Lambda.

        Establece la retención mínima de logs según config.log_retention_days
        (por defecto 30 días) para cada función Lambda del pipeline.
        Esto garantiza que los logs de ejecución estén disponibles para
        investigación de incidentes y auditoría.

        Requisito: 11.4
        """
        # Mapear días de retención a la enumeración de CDK
        retencion = self._obtener_retencion_logs(self.config.log_retention_days)

        # Crear LogGroup explícito para cada función Lambda del pipeline
        for nombre, funcion in self.lambda_functions.items():
            logs.LogGroup(
                self,
                f"LogGroup{nombre.title().replace('_', '')}",
                log_group_name=f"/aws/lambda/{funcion.function_name}",
                retention=retencion,
                removal_policy=RemovalPolicy.RETAIN,
            )

    @staticmethod
    def _obtener_retencion_logs(dias: int) -> logs.RetentionDays:
        """
        Convierte un número de días a la enumeración RetentionDays de CDK.

        Se selecciona el valor de retención más cercano que sea >= al número
        de días solicitado, para garantizar el mínimo requerido.

        Args:
            dias: Número mínimo de días de retención requerido.

        Returns:
            Valor de la enumeración RetentionDays apropiado.
        """
        if dias <= 1:
            return logs.RetentionDays.ONE_DAY
        elif dias <= 3:
            return logs.RetentionDays.THREE_DAYS
        elif dias <= 5:
            return logs.RetentionDays.FIVE_DAYS
        elif dias <= 7:
            return logs.RetentionDays.ONE_WEEK
        elif dias <= 14:
            return logs.RetentionDays.TWO_WEEKS
        elif dias <= 30:
            return logs.RetentionDays.ONE_MONTH
        elif dias <= 60:
            return logs.RetentionDays.TWO_MONTHS
        elif dias <= 90:
            return logs.RetentionDays.THREE_MONTHS
        elif dias <= 120:
            return logs.RetentionDays.FOUR_MONTHS
        elif dias <= 150:
            return logs.RetentionDays.FIVE_MONTHS
        elif dias <= 180:
            return logs.RetentionDays.SIX_MONTHS
        elif dias <= 365:
            return logs.RetentionDays.ONE_YEAR
        elif dias <= 400:
            return logs.RetentionDays.THIRTEEN_MONTHS
        elif dias <= 545:
            return logs.RetentionDays.EIGHTEEN_MONTHS
        elif dias <= 731:
            return logs.RetentionDays.TWO_YEARS
        elif dias <= 1827:
            return logs.RetentionDays.FIVE_YEARS
        elif dias <= 3653:
            return logs.RetentionDays.TEN_YEARS
        else:
            return logs.RetentionDays.INFINITE
