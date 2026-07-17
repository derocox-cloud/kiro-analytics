"""
Definición del State Machine de Step Functions para el pipeline de analytics.

Este módulo define el flujo de orquestación completo:
ValidateInput → CheckDuplicate → ParallelCollection → ProcessMetrics →
CheckAIFlag → [AnalyzeAI | GenerateReports] → PublishReports → UpdateIndex →
Notify → EmitMetrics → CleanupTemp

Incluye manejo de errores con reintentos exponenciales y flujo de fallo.

Requisitos: 1.1, 1.2, 4.4
"""

from typing import NamedTuple

from aws_cdk import (
    Duration,
    aws_lambda as _lambda,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
)
from constructs import Construct


class LambdaFunctions(NamedTuple):
    """Funciones Lambda requeridas por el state machine."""

    validate_input: _lambda.IFunction
    check_duplicate: _lambda.IFunction
    collect_user_reports: _lambda.IFunction
    collect_analytics: _lambda.IFunction
    collect_prompts: _lambda.IFunction
    process_metrics: _lambda.IFunction
    analyze_ai: _lambda.IFunction
    generate_reports: _lambda.IFunction
    publish_reports: _lambda.IFunction
    update_index: _lambda.IFunction
    notify: _lambda.IFunction
    notify_failure: _lambda.IFunction
    emit_metrics: _lambda.IFunction
    cleanup_temp: _lambda.IFunction


# Configuración de reintentos estándar (backoff exponencial: 5s, 10s, 20s)
_RETRY_CONFIG = {
    "interval": Duration.seconds(5),
    "max_attempts": 3,
    "backoff_rate": 2.0,
}


def _crear_lambda_invoke(
    scope: Construct,
    id_estado: str,
    funcion_lambda: _lambda.IFunction,
    *,
    resultado_path: str = "$",
    payload: sfn.TaskInput = None,
    comentario: str = "",
) -> tasks.LambdaInvoke:
    """
    Crea una invocación Lambda con la configuración estándar de reintentos.

    Args:
        scope: Scope del construct CDK.
        id_estado: Identificador único del estado.
        funcion_lambda: Función Lambda a invocar.
        resultado_path: Path donde almacenar el resultado en el estado.
        payload: Input personalizado para la Lambda (opcional).
        comentario: Comentario descriptivo del estado.

    Returns:
        Tarea LambdaInvoke configurada con reintentos exponenciales.
    """
    kwargs = {
        "lambda_function": funcion_lambda,
        "result_path": resultado_path,
        "comment": comentario,
    }

    if payload is not None:
        kwargs["payload"] = payload

    invoke = tasks.LambdaInvoke(scope, id_estado, **kwargs)

    # Configurar reintentos con backoff exponencial (5s, 10s, 20s)
    invoke.add_retry(
        errors=["States.ALL"],
        interval=_RETRY_CONFIG["interval"],
        max_attempts=_RETRY_CONFIG["max_attempts"],
        backoff_rate=_RETRY_CONFIG["backoff_rate"],
    )

    return invoke


class PipelineStateMachine(Construct):
    """
    Construct que define el state machine del pipeline de analytics.

    Flujo principal:
    1. ValidateInput → CheckDuplicate
    2. ParallelCollection (3 ramas: UserReports, Analytics, Prompts)
    3. ProcessMetrics
    4. CheckAIFlag (Choice) → AnalyzeAI O GenerateReports
    5. GenerateReports → PublishReports → UpdateIndex
    6. Notify → EmitMetrics → CleanupTemp

    Manejo de errores:
    - Cada estado tiene retry con backoff exponencial (5s, 10s, 20s)
    - En fallo, transición a: FailExecution → NotifyFailure → EmitMetrics → CleanupTemp
    - Fallo de AI → resultado degradado (pipeline continúa)
    - Fallo de publicación → continúa con indicador

    Timeout global: 10 minutos.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        lambdas: LambdaFunctions,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self._lambdas = lambdas

        # Construir el state machine
        self.state_machine = self._construir_state_machine()

    def _construir_state_machine(self) -> sfn.StateMachine:
        """Construye y retorna el state machine completo."""
        # Definir la cadena de fallo (reutilizable por los catch blocks)
        cadena_fallo = self._crear_cadena_fallo()

        # Definir el flujo principal
        definicion = self._crear_flujo_principal(cadena_fallo)

        # Crear el state machine con timeout global de 10 minutos
        state_machine = sfn.StateMachine(
            self,
            "PipelineOrquestador",
            state_machine_name="kiro-analytics-pipeline",
            definition_body=sfn.DefinitionBody.from_chainable(definicion),
            timeout=Duration.minutes(15),
            comment="Pipeline de analytics de Kiro - Orquestador Step Functions",
        )

        return state_machine

    def _crear_cadena_fallo(self) -> sfn.Chain:
        """
        Crea la cadena de estados para manejo de fallos.

        Flujo: FailExecution → NotifyFailure → EmitMetrics → CleanupTemp
        """
        # Estado de marcado de fallo
        fail_execution = sfn.Pass(
            self,
            "FailExecution",
            comment="Marcar ejecución como fallida",
            result=sfn.Result.from_object({"status": "FAILED"}),
            result_path="$.execution_status",
        )

        # Notificar fallo (sin reintentos - best effort)
        notify_failure = tasks.LambdaInvoke(
            self,
            "NotifyFailure",
            lambda_function=self._lambdas.notify_failure,
            result_path="$.notification_result",
            comment="Enviar notificación de fallo",
        )
        # La notificación de fallo no debe bloquear; si falla, continuar
        notify_failure.add_catch(
            handler=self._crear_emit_metrics_fallo(),
            errors=["States.ALL"],
            result_path="$.notify_error",
        )

        # Emitir métricas de la ejecución fallida
        emit_metrics_fallo = _crear_lambda_invoke(
            self,
            "EmitMetricsFallo",
            self._lambdas.emit_metrics,
            resultado_path="$.metrics_result",
            comentario="Emitir métricas de ejecución fallida",
        )

        # Limpiar datos temporales
        cleanup_temp_fallo = _crear_lambda_invoke(
            self,
            "CleanupTempFallo",
            self._lambdas.cleanup_temp,
            resultado_path="$.cleanup_result",
            comentario="Limpiar datos temporales tras fallo",
        )

        # Encadenar flujo de fallo
        cadena = (
            fail_execution
            .next(notify_failure)
            .next(emit_metrics_fallo)
            .next(cleanup_temp_fallo)
        )

        return cadena

    def _crear_emit_metrics_fallo(self) -> sfn.Chain:
        """
        Crea cadena EmitMetrics → CleanupTemp para usar como catch
        cuando NotifyFailure falla.
        """
        emit_metrics_catch = _crear_lambda_invoke(
            self,
            "EmitMetricsFalloCatch",
            self._lambdas.emit_metrics,
            resultado_path="$.metrics_result",
            comentario="Emitir métricas (tras fallo de notificación)",
        )

        cleanup_temp_catch = _crear_lambda_invoke(
            self,
            "CleanupTempFalloCatch",
            self._lambdas.cleanup_temp,
            resultado_path="$.cleanup_result",
            comentario="Limpiar datos temporales (tras fallo de notificación)",
        )

        return emit_metrics_catch.next(cleanup_temp_catch)

    def _crear_flujo_principal(self, cadena_fallo: sfn.Chain) -> sfn.Chain:
        """
        Crea el flujo principal del pipeline.

        Flujo: ValidateInput → CheckDuplicate → ParallelCollection →
               ProcessMetrics → CheckAIFlag → [AnalyzeAI] → GenerateReports →
               PublishReports → UpdateIndex → Notify → EmitMetrics → CleanupTemp
        """
        # --- Estado 1: Validar entrada ---
        validate_input = _crear_lambda_invoke(
            self,
            "ValidateInput",
            self._lambdas.validate_input,
            resultado_path="$.validation",
            comentario="Validar parámetros de entrada del pipeline",
        )
        validate_input.add_catch(
            handler=cadena_fallo,
            errors=["States.ALL"],
            result_path="$.error",
        )

        # --- Estado 2: Verificar duplicados ---
        check_duplicate = _crear_lambda_invoke(
            self,
            "CheckDuplicate",
            self._lambdas.check_duplicate,
            resultado_path="$.duplicate_check",
            comentario="Verificar que no existe ejecución duplicada activa",
        )
        check_duplicate.add_catch(
            handler=cadena_fallo,
            errors=["States.ALL"],
            result_path="$.error",
        )

        # --- Estado 3: Recolección paralela ---
        recoleccion_paralela = self._crear_recoleccion_paralela()
        recoleccion_paralela.add_catch(
            handler=cadena_fallo,
            errors=["States.ALL"],
            result_path="$.error",
        )

        # --- Estado 4: Procesar métricas ---
        process_metrics = _crear_lambda_invoke(
            self,
            "ProcessMetrics",
            self._lambdas.process_metrics,
            resultado_path="$.processing",
            comentario="Procesar y agregar métricas por usuario",
        )
        process_metrics.add_catch(
            handler=cadena_fallo,
            errors=["States.ALL"],
            result_path="$.error",
        )

        # --- Estado 5: Choice para flag de análisis AI ---
        check_ai_flag = sfn.Choice(
            self,
            "CheckAIFlag",
            comment="Evaluar si el análisis AI está habilitado",
        )

        # Rama: Análisis AI habilitado
        analyze_ai = _crear_lambda_invoke(
            self,
            "AnalyzeAI",
            self._lambdas.analyze_ai,
            resultado_path="$.ai_analysis",
            comentario="Ejecutar análisis AI con Bedrock",
        )
        # Si el análisis AI falla, continuar con resultado degradado
        analyze_ai_fallback = sfn.Pass(
            self,
            "AnalyzeAIFallback",
            comment="Resultado degradado: análisis AI no disponible",
            result=sfn.Result.from_object({
                "available": False,
                "reason": "AI analysis failed after retries - degraded result",
            }),
            result_path="$.ai_analysis",
        )
        analyze_ai.add_catch(
            handler=analyze_ai_fallback,
            errors=["States.ALL"],
            result_path="$.ai_error",
        )

        # --- Estado 6: Generar reportes ---
        generate_reports = _crear_lambda_invoke(
            self,
            "GenerateReports",
            self._lambdas.generate_reports,
            resultado_path="$.reports",
            comentario="Generar reportes HTML y CSV",
        )
        generate_reports.add_catch(
            handler=cadena_fallo,
            errors=["States.ALL"],
            result_path="$.error",
        )

        # --- Estado 7: Publicar reportes ---
        publish_reports = _crear_lambda_invoke(
            self,
            "PublishReports",
            self._lambdas.publish_reports,
            resultado_path="$.publication",
            comentario="Publicar reportes en sitio web estático",
        )
        # Si la publicación falla, continuar con indicador (no es crítico)
        publish_fallback = sfn.Pass(
            self,
            "PublishReportsFallback",
            comment="Publicación falló - continuar con indicador",
            result=sfn.Result.from_object({
                "published": False,
                "reason": "Publication failed - continuing with indicator",
            }),
            result_path="$.publication",
        )
        publish_reports.add_catch(
            handler=publish_fallback,
            errors=["States.ALL"],
            result_path="$.publish_error",
        )

        # --- Estado 8: Actualizar índice ---
        update_index = _crear_lambda_invoke(
            self,
            "UpdateIndex",
            self._lambdas.update_index,
            resultado_path="$.index_update",
            comentario="Actualizar página índice del sitio de reportes",
        )
        update_index.add_catch(
            handler=publish_fallback,
            errors=["States.ALL"],
            result_path="$.index_error",
        )

        # --- Estado 9: Notificar éxito ---
        notify = tasks.LambdaInvoke(
            self,
            "Notify",
            lambda_function=self._lambdas.notify,
            result_path="$.notification",
            comment="Enviar notificación de éxito",
        )
        # Notificación es best-effort; si falla, no afecta estado del pipeline
        notify_pass = sfn.Pass(
            self,
            "NotifyFallback",
            comment="Notificación falló - no afecta estado del pipeline",
            result=sfn.Result.from_object({"notified": False}),
            result_path="$.notification",
        )
        notify.add_catch(
            handler=notify_pass,
            errors=["States.ALL"],
            result_path="$.notify_error",
        )

        # --- Estado 10: Emitir métricas ---
        emit_metrics = _crear_lambda_invoke(
            self,
            "EmitMetrics",
            self._lambdas.emit_metrics,
            resultado_path="$.metrics_result",
            comentario="Emitir métricas personalizadas a CloudWatch",
        )

        # --- Estado 11: Limpiar temporales ---
        cleanup_temp = _crear_lambda_invoke(
            self,
            "CleanupTemp",
            self._lambdas.cleanup_temp,
            resultado_path="$.cleanup_result",
            comentario="Eliminar datos temporales de S3",
        )

        # --- Ensamblar flujo con Choice state ---
        # Rama AI: AnalyzeAI → GenerateReports
        ai_branch = analyze_ai.next(generate_reports)
        # El fallback de AI también va a GenerateReports
        analyze_ai_fallback.next(generate_reports)

        # Rama sin AI: directamente a GenerateReports (necesita un Pass intermedio)
        skip_ai = sfn.Pass(
            self,
            "SkipAIAnalysis",
            comment="AI deshabilitado - omitir análisis",
            result=sfn.Result.from_object({
                "available": False,
                "reason": "AI analysis disabled by configuration",
            }),
            result_path="$.ai_analysis",
        )
        no_ai_branch = skip_ai.next(generate_reports)

        # Configurar Choice: verificar $.ai_analysis == true
        check_ai_flag.when(
            sfn.Condition.boolean_equals("$.ai_analysis", True),
            ai_branch,
        )
        check_ai_flag.otherwise(no_ai_branch)

        # Flujo post-reportes (compartido por ambas ramas del Choice)
        post_reports = (
            publish_reports
            .next(update_index)
            .next(notify)
        )

        # El NotifyFallback continúa al mismo punto que Notify
        notify_pass.next(emit_metrics)

        # Flujo final
        post_notify = emit_metrics.next(cleanup_temp)

        # Conectar GenerateReports → PublishReports
        generate_reports.next(post_reports)

        # Conectar Notify → EmitMetrics
        notify.next(post_notify)

        # PublishReportsFallback → Notify (continúa el flujo)
        publish_fallback.next(notify)

        # --- Ensamblar flujo principal completo ---
        flujo_principal = (
            validate_input
            .next(check_duplicate)
            .next(recoleccion_paralela)
            .next(process_metrics)
            .next(check_ai_flag)
        )

        return flujo_principal

    def _crear_recoleccion_paralela(self) -> sfn.Parallel:
        """
        Crea el estado Parallel con 3 ramas para recolección simultánea.

        Ramas:
        - CollectUserReports: Recolectar datos de user_report
        - CollectAnalytics: Recolectar datos de by_user_analytic
        - CollectPrompts: Recolectar datos de prompt-metadata

        Cada rama tiene reintentos con backoff exponencial.
        Si una rama falla tras reintentos, toda la recolección falla.
        """
        parallel = sfn.Parallel(
            self,
            "ParallelCollection",
            comment="Recolección paralela de datos desde S3 (3 fuentes)",
            result_path="$.collection_results",
        )

        # Rama 1: Recolectar User Reports
        collect_user_reports = _crear_lambda_invoke(
            self,
            "CollectUserReports",
            self._lambdas.collect_user_reports,
            resultado_path="$",
            comentario="Recolectar datos de user_report desde S3",
        )

        # Rama 2: Recolectar Analytics
        collect_analytics = _crear_lambda_invoke(
            self,
            "CollectAnalytics",
            self._lambdas.collect_analytics,
            resultado_path="$",
            comentario="Recolectar datos de by_user_analytic desde S3",
        )

        # Rama 3: Recolectar Prompts
        collect_prompts = _crear_lambda_invoke(
            self,
            "CollectPrompts",
            self._lambdas.collect_prompts,
            resultado_path="$",
            comentario="Recolectar datos de prompt-metadata desde S3",
        )

        # Agregar ramas al estado paralelo
        parallel.branch(collect_user_reports)
        parallel.branch(collect_analytics)
        parallel.branch(collect_prompts)

        # Reintentos a nivel del estado paralelo
        parallel.add_retry(
            errors=["States.ALL"],
            interval=_RETRY_CONFIG["interval"],
            max_attempts=_RETRY_CONFIG["max_attempts"],
            backoff_rate=_RETRY_CONFIG["backoff_rate"],
        )

        return parallel
