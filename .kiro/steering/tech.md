---
inclusion: always
---

# Tech Stack

## Language & runtime
- Python 3.9+ (recommend 3.13; Lambda functions run on `python3.13` by default, configurable in `StackConfig`).
- Uses `from __future__ import annotations` in modules with dataclasses/type hints.

## Infrastructure
- AWS CDK v2 (Python) for IaC — see `infrastructure/`.
- Deployed resources: Lambda (9 functions, one per pipeline stage), Step Functions (orchestration), S3 (logs source, reports, static site), DynamoDB (on-demand, processed metrics), EventBridge (scheduling), Bedrock (AI analysis), CloudFront (site with Basic Auth), SNS (email notifications), CloudWatch (logs/metrics/alarms).
- Lambda code is bundled from the repo root (via CDK `BundlingOptions`, Docker-based with a local-bundling fallback in `_BundlingLocal`) to preserve `from src.X import ...` imports.
- IAM: every Lambda gets its own role with least-privilege, resource-scoped policies (no wildcard actions/resources) defined inline in `pipeline_stack.py`.

## Key dependencies
- `boto3` — AWS SDK, used with dependency-injected clients (`s3_client`, `dynamodb_client`, `sns_client`, etc.) for testability.
- `aws-cdk-lib` / `constructs` — CDK infra (optional extra: `cdk`).
- `pytest` — test runner.
- `hypothesis` — property-based testing.
- `moto` — mocked AWS services for integration tests.

Install dev + CDK deps: `pip install -e ".[dev,cdk]"`.

## Common commands

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,cdk]"

# Tests
pytest                      # full suite
pytest tests/unit/          # unit tests only
pytest tests/pbt/           # property-based tests only
pytest tests/integration/   # integration tests only (moto-mocked AWS)

# CDK
cdk bootstrap aws://<ACCOUNT_ID>/us-east-1
PYTHONPATH=. cdk synth --app "python3 infrastructure/app.py"
PYTHONPATH=. cdk deploy KiroAnalyticsPipeline --app "python3 infrastructure/app.py"

# Manual pipeline execution (after deploy)
aws stepfunctions start-execution \
  --state-machine-arn <STATE_MACHINE_ARN> \
  --input '{"period": "weekly", "reference_date": "YYYY-MM-DD", "ai_analysis": true}'
```

## Testing conventions
- Test files: `test_*.py`, functions `test_*`, classes `Test*` (see `[tool.pytest.ini_options]` in `pyproject.toml`).
- Property-based tests live in `tests/pbt/` and use Hypothesis (`@given`, `strategies as st`). Each PBT file documents which correctness property/requirement it validates in a header comment (e.g. `# Feature: ..., Property N: ... # Validates: Requirements X.Y`).
- Integration tests in `tests/integration/` use `moto` to mock AWS services (S3, DynamoDB, SNS, etc.) rather than hitting real infrastructure.
- Lambda dependencies (S3/DynamoDB/SNS/Bedrock clients) are passed as parameters with defaults of `None`, so tests can inject mocked clients instead of monkeypatching `boto3`.

## Language/comment convention
- Docstrings, inline comments, and log messages throughout `src/` and `infrastructure/` are written in **Spanish**, following the existing codebase style. Match this when editing those files. Public-facing docs (README, this steering) are in English.
