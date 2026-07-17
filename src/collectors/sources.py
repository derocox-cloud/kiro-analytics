"""
Configuraciones específicas por fuente de datos para el pipeline de analytics.

Define las configuraciones de recolección para cada fuente S3:
- user_report: Archivos CSV con datos de créditos y uso por usuario
- by_user_analytic: Archivos CSV con métricas detalladas por usuario
- prompt-metadata: Archivos JSON.gz con metadata de prompts (máx 500/día)

También implementa la lectura del roster de usuarios desde S3.
"""
from __future__ import annotations

import os
from typing import Dict, List

from src.models import CollectorConfig, User, RosterValidationResult
from src.utils.s3_utils import download_csv
from src.validators.roster_validator import validate_roster


# =============================================================================
# Constantes de configuración S3
# =============================================================================

# Cuenta AWS y región por defecto — configurar con tus valores
ACCOUNT_ID: str = os.environ.get("AWS_ACCOUNT_ID", "<ACCOUNT_ID>")
REGION: str = os.environ.get("AWS_REGION", "us-east-1")

# Bucket de logs fuente
LOGS_BUCKET: str = f"dev-logs-prompt-kiro-{ACCOUNT_ID}-{REGION}-an"

# Prefijos base derivados del script original
_LOGS_PREFIX: str = f"dev-kiro-logs/AWSLogs/{ACCOUNT_ID}/KiroLogs"
_PROMPTS_PREFIX: str = f"prompt-metadata/AWSLogs/{ACCOUNT_ID}/KiroLogs"

# Prefijos S3 específicos por fuente de datos
USER_REPORT_PREFIX: str = f"{_LOGS_PREFIX}/user_report/{REGION}"
ANALYTICS_PREFIX: str = f"{_LOGS_PREFIX}/by_user_analytic/{REGION}"
PROMPTS_PREFIX: str = f"{_PROMPTS_PREFIX}/GenerateAssistantResponse/{REGION}"


# =============================================================================
# Configuraciones de recolectores
# =============================================================================

def get_source_configs() -> Dict[str, CollectorConfig]:
    """
    Retorna las configuraciones de recolección para cada fuente de datos.

    Returns:
        Diccionario con clave el nombre de la fuente y valor su CollectorConfig.
    """
    return {
        "user_report": CollectorConfig(
            source_type="user_report",
            s3_prefix=USER_REPORT_PREFIX,
            file_extension=".csv",
            max_files_per_day=0,  # Sin límite
        ),
        "by_user_analytic": CollectorConfig(
            source_type="by_user_analytic",
            s3_prefix=ANALYTICS_PREFIX,
            file_extension=".csv",
            max_files_per_day=0,  # Sin límite
        ),
        "prompt-metadata": CollectorConfig(
            source_type="prompt-metadata",
            s3_prefix=PROMPTS_PREFIX,
            file_extension=".json.gz",
            max_files_per_day=500,  # Máximo 500 archivos por día
        ),
    }


def get_config_for_source(source_name: str) -> CollectorConfig:
    """
    Obtiene la configuración de recolección para una fuente específica.

    Args:
        source_name: Nombre de la fuente ("user_report", "by_user_analytic", "prompt-metadata").

    Returns:
        CollectorConfig correspondiente a la fuente.

    Raises:
        ValueError: Si el nombre de fuente no es válido.
    """
    configs = get_source_configs()
    if source_name not in configs:
        fuentes_validas = ", ".join(configs.keys())
        raise ValueError(
            f"Fuente de datos no válida: '{source_name}'. "
            f"Fuentes válidas: {fuentes_validas}"
        )
    return configs[source_name]


# =============================================================================
# Lectura de roster desde S3
# =============================================================================

def read_roster_from_s3(s3_client, bucket: str, key: str) -> List[User]:
    """
    Lee y parsea el archivo CSV de roster de usuarios desde S3.

    Descarga el archivo CSV desde la ubicación parametrizada en S3,
    valida su estructura usando el roster_validator, y retorna la lista
    de usuarios parseados.

    Args:
        s3_client: Cliente boto3 de S3 configurado.
        bucket: Nombre del bucket S3 donde se encuentra el roster.
        key: Clave (ruta) del archivo de roster dentro del bucket.

    Returns:
        Lista de objetos User parseados del roster.

    Raises:
        FileNotFoundError: Si el archivo no existe en la ubicación S3 especificada.
        ValueError: Si el archivo no es un CSV válido o no cumple con la estructura requerida.
    """
    # Descargar contenido CSV desde S3
    try:
        csv_content = download_csv(s3_client, bucket, key)
    except s3_client.exceptions.NoSuchKey:
        raise FileNotFoundError(
            f"Archivo de roster no encontrado en s3://{bucket}/{key}"
        )
    except Exception as e:
        # Manejar otros errores de S3 (permisos, bucket no existe, etc.)
        error_code = getattr(getattr(e, "response", {}), "get", lambda *a: None)
        if hasattr(e, "response"):
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey" or error_code == "404":
                raise FileNotFoundError(
                    f"Archivo de roster no encontrado en s3://{bucket}/{key}"
                )
        raise

    # Validar estructura del CSV usando el roster_validator
    resultado: RosterValidationResult = validate_roster(csv_content)

    if not resultado.valid:
        raise ValueError(
            f"Roster inválido en s3://{bucket}/{key}: {resultado.error}"
        )

    return resultado.users
