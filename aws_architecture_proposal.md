# AWS Automation & Workflow Architecture Proposal
### Scheduling • Orchestration • Compute

---

## 1. Executive Summary

This document presents a recommended AWS architecture for deploying a Java-based scheduled automation and workflow system. The proposed solution leverages AWS managed services to minimize operational overhead, maximize reliability, and provide cost-efficient compute.

The architecture consists of three layers:

- **Scheduling Layer** — Amazon EventBridge triggers the workflow on a cron schedule
- **Orchestration Layer** — AWS Step Functions coordinates all workflow steps using direct integrations where possible
- **Compute Layer** — AWS Lambda (Java) used **only where logic or missing integrations demand it** (2 Lambdas max)
- **State Store** — Amazon DynamoDB persists job config and execution state

> **Key Design Principle:** Step Functions has native direct integrations with DynamoDB, ECS, and SNS. Lambda should only be used where no direct integration exists or where custom logic is required. This reduces cost, cold starts, and code maintenance.

---

## 2. Architecture Overview

### 2.1 High-Level Flow

```
EventBridge (cron every minute)
        ↓
Lambda — Gatekeeper [JAVA] ← Lambda #1 (only Lambda needed here)
    ├── Read entities from DynamoDB
    ├── Idempotency check (is job already RUNNING?)
    └── Start Step Functions with config payload
        ↓
Step Functions — State Machine
    ├── Get Config       → DynamoDB Direct Integration  (no Lambda)
    ├── Job Runner?      → Choice State                 (no Lambda)
    │   ├── S32S path → Run ECS Task → Run DBR Job
    │   └── S2S3 path → Run ECS Task → Run DBR Job
    ├── Run ECS Task     → ECS Direct Integration       (no Lambda)
    ├── Run DBR Job      → Lambda [JAVA] ← Lambda #2 (Databricks bridge)
    ├── Wait & Monitor   → .sync integration pattern    (no Lambda)
    ├── Update State     → DynamoDB Direct Integration  (no Lambda)
    └── Notify           → SNS Direct Integration       (no Lambda)
```

> **Only 2 Lambda functions are needed** — the Gatekeeper and the Databricks job caller. Everything else uses Step Functions native direct integrations.

### 2.2 Layer Breakdown

| Layer | Service | Lambda Needed? | Responsibility |
|---|---|---|---|
| Scheduling | Amazon EventBridge | ❌ No | Triggers workflow on cron/rate schedule |
| Gatekeeper | AWS Lambda (Java) | ✅ Yes — Lambda #1 | Idempotency check + starts Step Functions |
| State Store | Amazon DynamoDB | ❌ No | Stores job config, entity list, execution state |
| Orchestration | AWS Step Functions | ❌ No | Coordinates all steps with error handling |
| Get Config | DynamoDB Direct Integration | ❌ No | Step Functions reads config natively |
| Job Runner Branch | Choice State | ❌ No | Built-in Step Functions branching — no compute |
| Run ECS Task | ECS Direct Integration | ❌ No | Step Functions starts ECS tasks natively |
| Run DBR Job | AWS Lambda (Java) | ✅ Yes — Lambda #2 | No native Databricks integration — Lambda bridges the gap |
| Wait & Monitor | .sync integration | ❌ No | Step Functions waits natively using .sync pattern |
| Update State | DynamoDB Direct Integration | ❌ No | Step Functions writes result to DynamoDB natively |
| Notification | Amazon SNS Direct Integration | ❌ No | Step Functions publishes to SNS natively |

---

## 3. Step Functions Workflow Design

### 3.1 State Machine Steps

| Step | State Type | Integration | Lambda Needed? | Description |
|---|---|---|---|---|
| Get Config | Task | DynamoDB Direct | ❌ No | Reads config record from DynamoDB table using `dynamodb:GetItem` — output passed as input to next step |
| Job Runner? | Choice | Built-in Choice State | ❌ No | Reads `jobRunner` field from Get Config output and branches to S32S or S2S3 path |
| Run ECS Task | Task | ECS Direct (.sync) | ❌ No | Step Functions starts and waits for ECS task |
| Run DBR Job | Task | Lambda (Java) | ✅ Yes | No native Databricks integration — Lambda calls DBR REST API |
| Wait & Monitor | Task | .sync pattern | ❌ No | Step Functions polls natively until job completes |
| Update State | Task | DynamoDB Direct | ❌ No | Step Functions writes result to DynamoDB natively |
| Notify | Task | SNS Direct | ❌ No | Step Functions publishes to SNS natively |

### 3.2 Error Handling Strategy

- Add **Retry** with exponential backoff on Lambda and ECS Task steps
- Add **Catch** blocks to route failures to an SNS notification step
- Set **Timeout** on each step to prevent stalled executions
- Use **Heartbeat** on long-running Batch/ECS tasks to detect stalls

```json
"Retry": [
  {
    "ErrorEquals": ["Lambda.ServiceException", "States.TaskFailed"],
    "IntervalSeconds": 5,
    "MaxAttempts": 3,
    "BackoffRate": 2
  }
]
```

---

## 4. Step Functions Direct Integrations vs Lambda — Opinion & Findings

### The Core Rule

> **If Step Functions has a native direct integration for a service — skip Lambda entirely.** Lambda adds cold start latency, extra code to maintain, and unnecessary cost when a direct integration achieves the same result.

### Get Config → Job Runner Data Flow

This is how config data moves from DynamoDB into the Job Runner decision — entirely without Lambda:

**Step 1 — Get Config (DynamoDB Direct Integration)**

Step Functions calls DynamoDB directly using `dynamodb:GetItem`:

```json
"GetConfig": {
  "Type": "Task",
  "Resource": "arn:aws:states:::dynamodb:getItem",
  "Parameters": {
    "TableName": "job-config",
    "Key": {
      "jobId": { "S.$": "$.jobId" },
      "env":   { "S.$": "$.env" }
    }
  },
  "ResultPath": "$.config",
  "Next": "JobRunnerChoice"
}
```

**Step 2 — DynamoDB Returns Config Record**

```json
{
  "jobId": "automation-job-1",
  "env": "prod",
  "config": {
    "Item": {
      "jobRunner": { "S": "S32S" },
      "maxRetries": { "N": "3" },
      "timeout":    { "N": "900" }
    }
  }
}
```

**Step 3 — Job Runner? (Choice State reads config output)**

```json
"JobRunnerChoice": {
  "Type": "Choice",
  "Choices": [
    {
      "Variable": "$.config.Item.jobRunner.S",
      "StringEquals": "S32S",
      "Next": "RunECSTask_S32S"
    },
    {
      "Variable": "$.config.Item.jobRunner.S",
      "StringEquals": "S2S3",
      "Next": "RunECSTask_S2S3"
    }
  ],
  "Default": "NotifyFailure"
}
```

> No Lambda required. The config value `jobRunner` read from DynamoDB is used directly by the Choice state to decide the branch.



### Step-by-Step Assessment for Your Use Case

| Step | Use Lambda? | Recommended Approach | Reasoning |
|---|---|---|---|
| **Get Config** | ❌ No | DynamoDB Direct Integration | Step Functions reads a config record from DynamoDB table using `dynamodb:GetItem` — the result is passed directly as input to the Job Runner Choice state |
| **Job Runner? (Choice)** | ❌ No | Choice State | Inspects the `jobRunner` field returned from Get Config to decide which branch to take (S32S or S2S3) |
| **Run ECS Task** | ❌ No | ECS Direct Integration | Step Functions starts ECS tasks and waits via `.sync` pattern |
| **Run DBR Job** | ✅ Yes | Lambda (Java) | No native Databricks integration in AWS — Lambda is the right bridge |
| **Wait & Monitor** | ❌ No | `.sync` integration pattern | Step Functions waits natively — no polling Lambda loop needed |
| **Update State** | ❌ No | DynamoDB Direct Integration | Step Functions writes to DynamoDB natively with `dynamodb:PutItem` |
| **Notify** | ❌ No | SNS Direct Integration | Step Functions publishes to SNS natively |

### What the .sync Integration Pattern Means

Instead of writing a Lambda polling loop to check if ECS or a job is done, Step Functions handles this natively:

```json
"Resource": "arn:aws:states:::ecs:runTask.sync",
```

The `.sync` suffix tells Step Functions to **wait for the task to complete** before moving to the next step — no Lambda needed.

### Lambda Usage Summary

| Lambda | Role | Justification |
|---|---|---|
| **Lambda #1 — Gatekeeper** | Before Step Functions starts | Needs custom logic: idempotency check + dynamic payload construction |
| **Lambda #2 — DBR Job Caller** | Inside Step Functions (Run DBR Job step) | No native AWS integration for Databricks — Lambda calls the Databricks REST API |

**Total Lambdas needed: 2** — not one per step.

### Benefits of This Approach

| Benefit | Impact |
|---|---|
| Fewer Lambda cold starts | Faster overall workflow execution |
| Less code to write and maintain | Only 2 Java Lambda functions instead of 6+ |
| Lower cost | Direct integrations are cheaper than Lambda invocations |
| Simpler IAM | Fewer roles and permissions to manage |
| Better observability | Step Functions visual console shows all steps natively |



### When to Use Lambda

| Use Lambda When | Do NOT Use Lambda When |
|---|---|
| Task completes in **≤ 15 minutes** | Task runs **longer than 15 minutes** |
| Lightweight processing (small data) | Needs heavy CPU / memory (> 10GB RAM) |
| Stateless, event-driven operations | Requires persistent connections |
| Low infrastructure management needed | Large dependencies (> 250MB package) |
| Cost optimization (pay per invocation) | Consistent low-latency required (cold starts) |
| Simple validations, API calls, transforms | Large dataset batch processing |

### When to Use AWS Batch

| Use Batch When | Do NOT Use Batch When |
|---|---|
| Jobs run **longer than 15 minutes** | Tasks are short and lightweight |
| Needs high CPU / large memory | You want zero infrastructure management |
| Processing large datasets or files | App needs real-time event-driven response |
| Running parallel jobs across many workers | Budget is tight (Batch has higher baseline cost) |
| Existing Java JAR with complex dependencies | Workflow is simple enough for Lambda |
| Retry logic needed for failed jobs | Instant scaling with no warm-up needed |

### Quick Rule of Thumb

> - Job **< 15 min + lightweight** → **Lambda**
> - Job **> 15 min + heavy compute** → **AWS Batch**
> - Not sure? → **Start with Lambda**, move to Batch if you hit limits

---

## 5. Should You Use Lambda as the Gatekeeper?

### Recommendation: YES — Lambda is the right choice here

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Lambda (Java)** | Serverless, fast, direct DynamoDB + Step Functions SDK access, no infra | Cold start (~1-2s for Java) | ✅ Recommended |
| **EC2** | Full control, no cold start | Always-on cost, over-engineered for this task | ❌ Overkill |
| **Elastic Beanstalk** | Managed environment, good for Java apps | Always-on, not event-driven | ❌ Overkill |
| **EventBridge → Step Functions directly** | Simpler, no Lambda needed | Cannot do conditional logic (check DynamoDB first) | ⚠️ Only if no gatekeeper logic needed |

### Why Lambda wins as the gatekeeper:
- Triggered directly by EventBridge on schedule
- Can query DynamoDB to check if a job is already running (idempotency)
- Can pass dynamic input (entity list, config) into Step Functions
- Costs near zero — runs for a few seconds per invocation
- Handles Java runtime natively with full AWS SDK support

---

## 6. EventBridge Setup

### Cron Expression Examples

| Schedule | Expression |
|---|---|
| Every minute | `rate(1 minute)` |
| Every day at 9AM UTC | `cron(0 9 * * ? *)` |
| Weekdays at 9AM | `cron(0 9 ? * MON-FRI *)` |
| Every 6 hours | `cron(0 */6 * * ? *)` |
| First day of every month | `cron(0 0 1 * ? *)` |

### EventBridge → Step Functions IAM Policy (Required)

```json
{
  "Effect": "Allow",
  "Action": "states:StartExecution",
  "Resource": "arn:aws:states:REGION:ACCOUNT:stateMachine:YourStateMachine"
}
```

### Key EventBridge Settings

| Setting | Recommendation |
|---|---|
| Timezone | Set explicitly — default is UTC |
| Retry policy | Set max retries to 3 with backoff |
| Dead Letter Queue | Add SQS DLQ for failed trigger events |
| Target input | Pass `{ "env": "prod", "jobType": "S32S" }` as static JSON |

---

## 7. DynamoDB Design

### Recommended Tables

| Table | Partition Key | Sort Key | Purpose |
|---|---|---|---|
| `job-config` | `jobId` | `env` | Stores job configuration per environment |
| `job-state` | `jobId` | `executionId` | Tracks execution status (RUNNING, SUCCESS, FAILED) |
| `entities` | `entityId` | `type` | Stores entities to be processed |

### Idempotency Check (Gatekeeper Lambda Logic)

```
1. Lambda triggered by EventBridge
2. Query DynamoDB job-state → is any job currently RUNNING?
   ├── YES → skip, do not start Step Functions (prevents overlapping runs)
   └── NO  → write RUNNING status → start Step Functions execution
```

---

## 8. Gotchas & What You Should Do

### Gotchas to Watch Out For

| Area | Gotcha | What To Do |
|---|---|---|
| **Lambda cold start** | Java has ~1-2s cold start delay | Use Provisioned Concurrency if latency is critical |
| **Step Functions payload** | Max input/output per step is 256KB | Store large data in S3, pass only the S3 key |
| **EventBridge timezone** | Default is UTC, not local time | Always set timezone explicitly in scheduler |
| **IAM permissions** | Each service needs explicit permissions | Create least-privilege IAM roles per service |
| **Overlapping executions** | EventBridge fires every minute regardless | Implement idempotency check in gatekeeper Lambda |
| **Step Functions cost** | Charged per state transition | Use Standard workflow; Express only for high-volume short jobs |
| **DynamoDB consistency** | Default reads are eventually consistent | Use strongly consistent reads for job-state checks |
| **Lambda timeout** | Default Lambda timeout is 3 seconds | Set timeout to match your expected execution time |
| **Step Functions history** | Execution history kept for 90 days only | Export to CloudWatch Logs for longer retention |
| **Java package size** | Lambda has 250MB deployment package limit | Use Lambda layers for shared dependencies |

### What You Should Do (Action Checklist)

- [ ] Set up EventBridge Scheduler with correct cron and timezone
- [ ] Create IAM role for EventBridge to invoke Lambda
- [ ] Create IAM role for Lambda to read DynamoDB and start Step Functions
- [ ] Create IAM role for Step Functions to invoke Lambda, ECS, SNS
- [ ] Implement idempotency check in gatekeeper Lambda (query job-state table)
- [ ] Define Step Functions state machine in Amazon States Language (ASL)
- [ ] Add Retry and Catch on every Task state in Step Functions
- [ ] Set appropriate Timeout on Lambda and Step Functions steps
- [ ] Add SNS topic for failure notifications and subscribe your team
- [ ] Enable CloudWatch Logs on Step Functions for full execution history
- [ ] Enable X-Ray tracing on Lambda and Step Functions for performance visibility
- [ ] Test with a manual Step Functions execution before enabling EventBridge
- [ ] Add DLQ (SQS) to EventBridge for failed trigger events

---

---

## 9. AWS Services That Integrate Directly with Step Functions

Step Functions supports native direct integrations with 200+ AWS services via the SDK integration type. No Lambda is needed for these calls. Below are the most relevant categories.

### Compute

| Service | Resource ARN | .sync Supported | When to Use |
|---|---|---|---|
| AWS Lambda | `:::lambda:invoke` | ✅ Yes | Custom logic or services with no native integration (e.g. Databricks) |
| Amazon ECS / Fargate | `:::ecs:runTask.sync` | ✅ Yes | Run containerised tasks and wait for completion |
| AWS Batch | `:::batch:submitJob.sync` | ✅ Yes | Heavy long-running jobs exceeding Lambda's 15-min limit |
| AWS Glue | `:::glue:startJobRun.sync` | ✅ Yes | ETL data transformation jobs — no polling Lambda needed |

### Messaging

| Service | Resource ARN | .sync Supported | When to Use |
|---|---|---|---|
| Amazon SNS | `:::sns:publish` | ❌ No | Publish notifications on success or failure |
| Amazon SQS | `:::sqs:sendMessage` | ❌ No | Send messages to decouple downstream consumers |
| Amazon EventBridge | `:::events:putEvents` | ❌ No | Emit custom events to trigger other workflows |

### Storage & Database

| Service | Resource ARN | .sync Supported | When to Use |
|---|---|---|---|
| Amazon DynamoDB | `:::dynamodb:getItem` / `putItem` | ❌ No | Read config, write job state — no Lambda needed |
| Amazon S3 | `:::s3:getObject` / `putObject` | ❌ No | Pass large payloads (>256KB) between steps via S3 key |

### ML & Analytics

| Service | Resource ARN | .sync Supported | When to Use |
|---|---|---|---|
| Amazon SageMaker | `:::sagemaker:createTrainingJob.sync` | ✅ Yes | ML training, batch transform, endpoint deployment |
| Amazon Athena | `:::athena:startQueryExecution.sync` | ✅ Yes | Run SQL analytics queries as a pipeline step |
| AWS Glue DataBrew | `:::databrew:startJobRun.sync` | ✅ Yes | No-code data cleaning and preparation jobs |

### API & Integration

| Service | Resource ARN | .sync Supported | When to Use |
|---|---|---|---|
| Amazon API Gateway | `:::apigateway:invoke` | ❌ No | Call REST APIs without Lambda glue code |
| AWS SDK (catch-all) | `:::aws-sdk:*` | Varies | 200+ AWS services callable directly — if an SDK call exists, Step Functions can make it |

### Containers & DevOps

| Service | Resource ARN | .sync Supported | When to Use |
|---|---|---|---|
| Amazon EKS | `:::eks:runJob.sync` | ✅ Yes | Run Kubernetes jobs on EKS clusters |
| AWS CodeBuild | `:::codebuild:startBuild.sync` | ✅ Yes | Trigger CI/CD builds as part of a workflow |

### What `.sync` Means

The `.sync` suffix on a Resource ARN tells Step Functions to **wait for the job to complete** before moving to the next state. Without it, Step Functions fires the call and immediately moves on (fire-and-forget).

```json
"Resource": "arn:aws:states:::ecs:runTask.sync"
```

> Use `.sync` on any step where the next step depends on the result — ECS tasks, Batch jobs, Glue jobs, SageMaker training, etc.

### How This Applies to Your Architecture

| Step in Your Workflow | Direct Integration Used |
|---|---|
| Get Config | `dynamodb:getItem` |
| Run ECS Task | `ecs:runTask.sync` |
| Run DBR Job | `lambda:invoke` (no native Databricks integration) |
| Update State | `dynamodb:putItem` |
| Notify | `sns:publish` |

All steps except the Databricks call use direct integrations — no extra Lambda required.

---

## 10. Cost Estimate (Daily Scheduled Job)

| Service | Usage Assumption | Estimated Cost/Month |
|---|---|---|
| EventBridge Scheduler | 1 trigger/minute = ~43,200/month | ~$0.01 |
| Lambda #1 (Gatekeeper) | 43,200 invocations × 2s | ~$0.10 |
| Step Functions (Standard) | 30 executions/day × 7 steps | ~$0.16 |
| Lambda #2 (DBR Job Caller) | 30 executions/day × 3s | ~$0.01 |
| DynamoDB | On-demand, low read/write volume | ~$1.00 |
| SNS | 30 notifications/day | ~$0.01 |
| **Total Estimate** | | **~$1.30–3/month** |

> Savings vs Lambda-per-step approach: replacing 5 Lambda steps with direct integrations reduces Step Functions + Lambda cost by ~60%.
> Cost will vary based on execution frequency, Lambda memory, and data volume.

---

## 11. Recommended Architecture (Final)


```
Amazon EventBridge (cron schedule)
        ↓
AWS Lambda #1 — Java Gatekeeper
    ├── Read entities from DynamoDB
    ├── Check if job already running (idempotency)
    └── Start Step Functions with config payload
        ↓
AWS Step Functions — Standard Workflow
    ├── Task: Get Config          → DynamoDB Direct Integration
    ├── Choice: Job Runner?       → Choice State (S32S or S2S3)
    │   ├── Task: Run ECS Task   → ECS Direct Integration (.sync)
    │   └── Task: Run DBR Job    → Lambda #2 (Java) — Databricks REST API
    ├── Task: Wait & Monitor      → .sync pattern (native polling)
    ├── Task: Update State        → DynamoDB Direct Integration
    └── Task: Notify              → SNS Direct Integration
```

### Why This Stack Works for You

| Requirement | How It's Met |
|---|---|
| Java-based app | Lambda supports Java 11/17/21 natively |
| Scheduled execution | EventBridge cron triggers reliably |
| No Docker | Lambda runs Java JARs directly, no containers |
| Workflow orchestration | Step Functions manages all steps |
| Minimal Lambda usage | Only 2 Lambdas — gatekeeper and Databricks caller |
| State persistence | DynamoDB stores config and execution state |
| Error handling | Step Functions Retry + Catch on every step |
| Cost efficiency | Serverless + direct integrations = pay only when running |
| Observability | CloudWatch + X-Ray for logs and tracing |
| No over-engineering | Direct integrations replace unnecessary Lambda functions |

---

*Document prepared for internal architecture review. Version 3.0*
