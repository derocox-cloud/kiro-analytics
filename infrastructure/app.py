#!/usr/bin/env python3
"""
Punto de entrada de la aplicación CDK del pipeline de analytics de Kiro.

Define la app CDK y instancia el stack principal con la configuración
de entorno.
"""

import aws_cdk as cdk

from infrastructure.pipeline_stack import PipelineStack, StackConfig


def main():
    """Crea la aplicación CDK con el stack del pipeline."""
    app = cdk.App()

    # =========================================================================
    # CONFIGURACIÓN — Editar con los valores de tu cuenta AWS
    # =========================================================================
    config = StackConfig(
        # Bucket donde están los logs de Kiro (formato: dev-logs-prompt-kiro-<ACCOUNT_ID>-<REGION>-an)
        logs_bucket="dev-logs-prompt-kiro-<ACCOUNT_ID>-<REGION>-an",

        # Tu cuenta AWS
        account_id="<ACCOUNT_ID>",
        region="us-east-1",

        # Correos para notificaciones del pipeline (1-10 destinatarios)
        notification_emails=[
            "admin@your-company.com",
        ],

        # Correos autorizados para acceder al sitio de reportes
        authorized_emails=[
            "admin@your-company.com",
        ],

        # Modelo de Bedrock (verificar disponibilidad en tu región)
        bedrock_model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",

        # Runtime Python para Lambda
        python_runtime="python3.13",

        # Retención de logs (días)
        log_retention_days=30,

        # Retención de reportes (días) — ciclo de vida S3
        report_retention_days=90,
    )

    # Instanciar el stack principal
    PipelineStack(
        app,
        "KiroAnalyticsPipeline",
        config=config,
        env=cdk.Environment(
            account=config.account_id,
            region=config.region,
        ),
    )

    app.synth()


if __name__ == "__main__":
    main()
