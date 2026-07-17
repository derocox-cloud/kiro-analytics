---
inclusion: always
---

# Product

Kiro Analytics Pipeline is a serverless AWS pipeline that generates usage analytics reports for teams using Kiro (the AI coding assistant) via Kiro subscriptions provisioned through the AWS Console.

## What it does

- Reads Kiro usage logs (prompt logging + user activity reports) from an S3 bucket managed by the Kiro AWS Console integration.
- Aggregates per-user metrics: credits used/remaining, conversations, messages, AI-generated code lines, inline completion acceptance, active days.
- Categorizes prompts by topic (Code, Infrastructure, Database, Testing, Frontend, etc.) and by intent (do/chat/spec).
- Optionally runs AI analysis of prompt samples using Amazon Bedrock (Claude Haiku 4.5) to produce narrative insights and adoption recommendations.
- Generates HTML and CSV reports for daily/weekly/monthly periods, stores them in S3, and publishes the HTML report to a CloudFront-fronted static site (Basic Auth protected).
- Sends success/failure email notifications via SNS and persists historical metrics in DynamoDB.
- Runs automatically on a schedule (weekly on Fridays, monthly on the 1st) via EventBridge, or can be triggered manually via Step Functions.

## Key design principle: graceful degradation

The pipeline is built to keep producing a usable report even when non-critical stages fail:
- Bedrock failure → report generated without the AI analysis section.
- Web publishing failure → report still available via S3 pre-signed URL.
- Notification failure → logged only, does not affect pipeline status.
- Only a failure in data collection causes the whole pipeline run to fail.

## Users

Internal to a team/organization running Kiro under an AWS Console-managed subscription. Report audience is typically engineering managers or admins tracking team adoption and usage against the Kiro Pro credit limit (1,000 credits/user/month).
