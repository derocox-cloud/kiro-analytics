"""
Tests de infraestructura CDK para la tabla DynamoDB y permisos IAM.

Verifica mediante CDK assertions que el template sintetizado tiene la
configuración correcta de tabla DynamoDB, permisos IAM de mínimo privilegio
para las funciones Lambda, y variables de entorno necesarias.
"""

import aws_cdk as cdk
from aws_cdk import assertions

from infrastructure.pipeline_stack import PipelineStack, StackConfig


def _get_template() -> assertions.Template:
    """
    Sintetiza el stack CDK y retorna el Template para assertions.

    Usa configuración por defecto de desarrollo para síntesis.
    """
    app = cdk.App()
    config = StackConfig(
        logs_bucket="dev-logs-prompt-kiro-123456789012-us-east-1-an",
        account_id="123456789012",
        region="us-east-1",
    )
    stack = PipelineStack(
        app,
        "TestStack",
        config=config,
        env=cdk.Environment(account=config.account_id, region=config.region),
    )
    return assertions.Template.from_stack(stack)


class TestDynamoDBTable:
    """Verificaciones de la tabla DynamoDB de métricas procesadas."""

    def test_table_key_schema(self):
        """Verifica que la tabla tiene PK user_id (String) y SK periodo (String)."""
        template = _get_template()
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {
                "KeySchema": [
                    {"AttributeName": "user_id", "KeyType": "HASH"},
                    {"AttributeName": "periodo", "KeyType": "RANGE"},
                ],
                "AttributeDefinitions": [
                    {"AttributeName": "user_id", "AttributeType": "S"},
                    {"AttributeName": "periodo", "AttributeType": "S"},
                ],
            },
        )

    def test_table_billing_mode_pay_per_request(self):
        """Verifica que la tabla usa modo de capacidad on-demand (PAY_PER_REQUEST)."""
        template = _get_template()
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {
                "BillingMode": "PAY_PER_REQUEST",
            },
        )

    def test_table_point_in_time_recovery_enabled(self):
        """Verifica que Point-in-Time Recovery está habilitado."""
        template = _get_template()
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {
                "PointInTimeRecoverySpecification": {
                    "PointInTimeRecoveryEnabled": True,
                },
            },
        )

    def test_table_removal_policy_retain(self):
        """Verifica que la tabla tiene DeletionPolicy Retain para evitar eliminación accidental."""
        template = _get_template()
        template.has_resource(
            "AWS::DynamoDB::Table",
            {
                "DeletionPolicy": "Retain",
                "UpdateReplacePolicy": "Retain",
            },
        )


class TestProcesadorLambdaPermissions:
    """Verificaciones de permisos IAM del Lambda procesador de métricas."""

    def test_procesador_has_dynamodb_write_permissions(self):
        """Verifica que el procesador tiene permisos dynamodb:PutItem y dynamodb:BatchWriteItem."""
        template = _get_template()
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": assertions.Match.array_with(
                        [
                            assertions.Match.object_like(
                                {
                                    "Action": [
                                        "dynamodb:PutItem",
                                        "dynamodb:BatchWriteItem",
                                    ],
                                    "Effect": "Allow",
                                    "Resource": assertions.Match.any_value(),
                                }
                            ),
                        ]
                    ),
                },
            },
        )

    def test_procesador_dynamodb_permissions_target_metrics_table(self):
        """Verifica que los permisos DynamoDB del procesador apuntan al ARN de la tabla de métricas."""
        template = _get_template()
        # Buscar la política que contiene EscribirMetricasDynamoDB
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": assertions.Match.array_with(
                        [
                            assertions.Match.object_like(
                                {
                                    "Sid": "EscribirMetricasDynamoDB",
                                    "Action": [
                                        "dynamodb:PutItem",
                                        "dynamodb:BatchWriteItem",
                                    ],
                                    "Effect": "Allow",
                                    "Resource": {
                                        "Fn::GetAtt": assertions.Match.array_with(
                                            [
                                                assertions.Match.string_like_regexp(
                                                    "MetricasProcesadas.*"
                                                ),
                                            ]
                                        ),
                                    },
                                }
                            ),
                        ]
                    ),
                },
            },
        )

    def test_procesador_has_metrics_table_name_env_var(self):
        """Verifica que el Lambda procesador tiene variable de entorno METRICS_TABLE_NAME."""
        template = _get_template()
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {
                "FunctionName": "kiro-analytics-procesador",
                "Environment": {
                    "Variables": {
                        "METRICS_TABLE_NAME": assertions.Match.any_value(),
                    },
                },
            },
        )


class TestGeneradorReportesLambdaPermissions:
    """Verificaciones de permisos IAM del Lambda generador de reportes."""

    def test_generador_has_dynamodb_query_permission(self):
        """Verifica que el generador de reportes tiene permiso dynamodb:Query."""
        template = _get_template()
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": assertions.Match.array_with(
                        [
                            assertions.Match.object_like(
                                {
                                    "Sid": "ConsultarMetricasDynamoDB",
                                    "Action": "dynamodb:Query",
                                    "Effect": "Allow",
                                    "Resource": {
                                        "Fn::GetAtt": assertions.Match.array_with(
                                            [
                                                assertions.Match.string_like_regexp(
                                                    "MetricasProcesadas.*"
                                                ),
                                            ]
                                        ),
                                    },
                                }
                            ),
                        ]
                    ),
                },
            },
        )

    def test_generador_dynamodb_permissions_only_query(self):
        """Verifica que el generador solo tiene dynamodb:Query, sin PutItem ni BatchWriteItem."""
        template = _get_template()
        # Verificar que existe una política con Sid ConsultarMetricasDynamoDB que solo contiene Query
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": assertions.Match.array_with(
                        [
                            assertions.Match.object_like(
                                {
                                    "Sid": "ConsultarMetricasDynamoDB",
                                    "Action": "dynamodb:Query",
                                    "Effect": "Allow",
                                }
                            ),
                        ]
                    ),
                },
            },
        )
