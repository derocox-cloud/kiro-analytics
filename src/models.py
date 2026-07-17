"""
Modelos de datos y tipos compartidos para el pipeline de analytics de Kiro.

Define las dataclasses utilizadas por todos los componentes del pipeline,
así como las constantes de configuración compartidas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# =============================================================================
# Constantes
# =============================================================================

# Periodos válidos para la ejecución del pipeline
VALID_PERIODS: List[str] = ["daily", "weekly", "monthly"]

# Límite de créditos mensuales por usuario (Kiro Pro)
CREDITS_PER_USER: int = 1000

# Máximo de caracteres en el payload enviado a Bedrock
MAX_BEDROCK_CHARS: int = 30000

# Máximo de muestras de prompts por usuario para análisis AI
MAX_SAMPLES_PER_USER: int = 15

# Categorías de prompts con keywords ordenadas por prioridad.
# La primera categoría cuyas keywords coincidan (case-insensitive, subcadena)
# es la que se asigna al prompt. Si ninguna coincide, se asigna "Otros".
PROMPT_CATEGORIES: Dict[str, List[str]] = {
    "Código": [
        "code", "función", "function", "class", "método", "variable",
        "import", "return", "loop", "array", "string", "error", "bug",
        "fix", "implement",
    ],
    "Infraestructura": [
        "aws", "cloud", "lambda", "s3", "ec2", "docker", "kubernetes",
        "terraform", "deploy", "pipeline", "ci/cd", "infra",
    ],
    "Base de Datos": [
        "database", "sql", "query", "table", "index", "dynamo",
        "postgres", "mongo", "redis", "migration",
    ],
    "Testing": [
        "test", "pytest", "unittest", "mock", "assert", "coverage",
        "hypothesis", "spec",
    ],
    "Documentación": [
        "document", "readme", "comment", "docstring", "wiki", "guide",
        "tutorial",
    ],
    "Refactoring": [
        "refactor", "clean", "optimize", "simplify", "rename", "extract",
        "move",
    ],
    "Frontend": [
        "html", "css", "react", "component", "ui", "ux", "style",
        "layout", "responsive",
    ],
    "Análisis": [
        "analy", "metric", "report", "dashboard", "chart", "graph",
        "statistic", "data",
    ],
    "Configuración": [
        "config", "setting", "env", "parameter", "variable", "secret",
        "credential",
    ],
}


# =============================================================================
# Modelos de datos
# =============================================================================

@dataclass
class PipelineInput:
    """Parámetros de entrada para una ejecución del pipeline."""

    period: str              # "daily" | "weekly" | "monthly"
    reference_date: str      # formato "YYYY-MM-DD"
    ai_analysis: bool = True
    output_format: str = "both"  # "html" | "csv" | "both"


@dataclass
class User:
    """Modelo de usuario del roster."""

    user_id: str
    username: str
    display_name: str
    email: str
    status: str              # "Enabled" | otro valor


@dataclass
class UserMetrics:
    """Métricas agregadas por usuario para un periodo dado."""

    user_id: str
    username: str
    display_name: str
    email: str
    credits_used: float
    credits_monthly: float
    credits_pct: float
    conversations: int
    total_messages: int
    days_active: int
    clients_used: List[str]
    chat_messages_sent: int
    ai_code_lines: int
    inline_suggestions: int
    inline_accepted: int
    prompt_count: int
    prompt_categories: Dict[str, int] = field(default_factory=dict)
    intents: Dict[str, int] = field(default_factory=dict)
    models: Dict[str, int] = field(default_factory=dict)


@dataclass
class CollectorConfig:
    """Configuración para un recolector de datos específico."""

    source_type: str          # "user_report" | "analytics" | "prompts"
    s3_prefix: str
    file_extension: str       # ".csv" | ".json.gz"
    max_files_per_day: int    # prompts: 500


@dataclass
class CollectionResult:
    """Resultado de la recolección de datos de una fuente."""

    source_type: str
    records: List[dict] = field(default_factory=list)
    file_count: int = 0
    data_size_bytes: int = 0
    errors: List[str] = field(default_factory=list)


@dataclass
class ProcessingResult:
    """Resultado del procesamiento y agregación de métricas."""

    user_metrics: List[UserMetrics] = field(default_factory=list)
    inactive_users: List[User] = field(default_factory=list)
    total_users_processed: int = 0
    processing_duration_seconds: float = 0.0


@dataclass
class AIAnalysisResult:
    """Resultado del análisis AI con Bedrock."""

    analysis_text: str
    available: bool
    model_used: str
    tokens_used: int
    duration_seconds: float
    error_message: Optional[str] = None


@dataclass
class ReportGenerationResult:
    """Resultado de la generación de reportes."""

    html_url: Optional[str] = None
    csv_url: Optional[str] = None
    html_s3_key: Optional[str] = None
    csv_s3_key: Optional[str] = None
    generation_duration_seconds: float = 0.0


@dataclass
class ExecutionResult:
    """Resultado completo de una ejecución del pipeline."""

    execution_id: str
    period: str
    reference_date: str
    status: str                    # "SUCCEEDED" | "FAILED"
    total_duration_seconds: float
    stage_durations: Dict[str, float] = field(default_factory=dict)
    users_processed: int = 0
    data_size_bytes: int = 0
    failure_stage: Optional[str] = None
    failure_message: Optional[str] = None
    report_urls: Optional[Dict[str, str]] = None
    timestamp: str = ""            # ISO 8601


@dataclass
class ReportMetadata:
    """Metadata de un reporte para la página índice."""

    filename: str
    period: str
    start_date: str
    end_date: str
    generated_at: str
    s3_key: str


@dataclass
class ScheduleParams:
    """Parámetros calculados para una ejecución programada."""

    period: str
    reference_date: str  # YYYY-MM-DD


@dataclass
class RosterValidationResult:
    """Resultado de la validación del archivo de roster CSV."""

    valid: bool
    users: List[User] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ValidationResult:
    """Resultado de la validación de parámetros de entrada del pipeline."""

    valid: bool
    params: Optional[PipelineInput] = None
    error: Optional[str] = None


@dataclass
class NotificationResult:
    """Resultado del envío de notificaciones."""

    success: bool
    error: Optional[str] = None
