---
inclusion: always
---

# Project Structure

```
kiro-analytics-public/
├── src/                        # Pipeline source code (imported as `src.X`, Spanish docstrings)
│   ├── pipeline.py              # run_pipeline(): local/testable orchestration entry point
│   ├── models.py                # Shared dataclasses (User, UserMetrics, ExecutionResult, ...) + constants (VALID_PERIODS, PROMPT_CATEGORIES, CREDITS_PER_USER)
│   ├── validators/               # Input params + roster CSV validation
│   ├── collectors/               # Reads raw logs from S3 (collector.py logic, sources.py config/roster loading)
│   ├── processors/               # categorizer.py (prompt topic/keyword classification), metrics_processor.py (aggregation), dynamodb_writer.py
│   ├── analyzers/                # ai_analyzer.py — Bedrock (Claude Haiku 4.5) prompt analysis
│   ├── generators/               # html_generator, csv_generator, report_storage (S3 + pre-signed URLs), site_publisher (CloudFront site), index_generator
│   ├── notifiers/                # notifier.py — SNS email notifications
│   ├── orchestrator/              # handler.py = Lambda entry point (mirrors pipeline.py but Lambda-native, with duplicate-execution check via DynamoDB and EventBridge completion events); metrics_emitter.py, retry_handler.py, temp_cleanup.py
│   └── utils/                    # date_utils, execution_summary, s3_utils, text_utils
├── infrastructure/               # AWS CDK app (IaC)
│   ├── app.py                    # CDK entry point — edit StackConfig here for real deployments
│   ├── pipeline_stack.py         # Main stack: DynamoDB table, S3 buckets, SNS topic, CloudFront, 9 Lambdas w/ scoped IAM roles
│   ├── state_machine.py          # Step Functions definition (LambdaFunctions NamedTuple + PipelineStateMachine construct)
│   ├── cdk.out/                   # CDK synth output (generated, do not hand-edit)
│   └── iam-policies/              # Reference IAM policy JSON for bootstrap/pipeline deploy roles
├── tests/
│   ├── unit/                     # Unit tests, one per src module roughly
│   ├── pbt/                       # Property-based tests (Hypothesis) — each documents the correctness property + requirement it validates
│   └── integration/                # moto-mocked AWS integration tests + CDK stack assertion tests
├── examples/
│   └── sample-report.html         # Example HTML report output (dummy data) for previewing report format
├── kiro-users-example.csv          # Example roster file format (Username, Display name, Status, Email, User ID)
└── pyproject.toml                 # Project metadata, dependencies, pytest config
```

## Architecture flow

Two parallel implementations of the same orchestration exist and must be kept in sync when changing pipeline stage order/logic:
- `src/pipeline.py` — `run_pipeline()`, used for local runs/tests, takes injectable AWS clients as function args.
- `src/orchestrator/handler.py` — `handler()`, the actual Lambda/Step Functions entry point; adds duplicate-execution locking (DynamoDB) and emits an EventBridge completion event.

Pipeline stage order (both implementations): validate input → read roster → collect (parallel: user_report, by_user_analytic, prompt-metadata from S3) → process/aggregate metrics → AI analysis (Bedrock, optional) → generate reports (HTML/CSV) → publish to site (CloudFront/S3) → update site index → notify (SNS) → emit metrics / cleanup temp data.

In `infrastructure/state_machine.py`, this same flow is mirrored as Step Functions states, each Lambda invoke wrapped with exponential-backoff retry (5s/10s/20s, 3 attempts) via `_crear_lambda_invoke`, plus `add_catch` fallbacks implementing graceful degradation (AI failure → degraded Pass state, publish failure → indicator Pass state, notify failure → best-effort Pass state).

## Conventions to follow when adding code
- New Lambda-backed pipeline stages: add the function under the matching `src/` subpackage, add a `lambda_handler` entry point, wire it into both `pipeline.py`/`handler.py` (business logic) and `pipeline_stack.py` + `state_machine.py` (infra + orchestration) if it needs its own Lambda.
- Shared types/constants go in `src/models.py`, not scattered across modules.
- New Lambda IAM policies must be resource-scoped (no `*` actions/resources), following the per-function `politica_*` pattern in `pipeline_stack.py`.
- New correctness-critical logic should get a matching property-based test in `tests/pbt/`, referencing the requirement/property it validates in a header comment, in addition to unit tests.
