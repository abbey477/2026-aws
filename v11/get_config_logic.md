# GetConfig Lambda — Logic Explained

## What It Does

GetConfig is the **first lambda** in the orchestrator Step Function. It
fetches two things from DynamoDB, merges them into a single payload, and
passes it downstream to PreStepsProcessor → RunnerTypeChoice → TriggerEcsJob.

1. **Job run metadata** — the current state of a run (status, timestamps, etc.)
2. **Job configuration** — how the job should be executed (runner type, parameters, etc.)

---

## Step-by-Step Flow

### 1. Receive the event from Step Functions

The event contains a `run_id` and optionally a `last_updated_time`:

```json
// Normal run — fetch the latest state
{ "run_id": "run-001" }

// Restart — fetch a specific historical state
{ "run_id": "run-001", "last_updated_time": "2024-03-15T10:00:00Z" }
```

### 2. Validate the input

```python
run_id = event.get("run_id")
if not run_id:
    raise ValueError("Missing required input: 'run_id'")
```

If `run_id` is missing, empty, or `null` → log error, write FAILED to
`app-jobLog`, raise exception. Step Functions catches it → HandleError.

### 3. Fetch job run metadata (Step 1)

Query the `app-jobRun` DynamoDB table to get the run's current state.

**Table schema:**
- PK: `run_id` (string)
- SK: `last_updated_time` (string, ISO-8601)

**The table is append-only** — each state change (WAITING → RUNNING →
COMPLETED → FAILED) creates a NEW row with a new `last_updated_time`.
This means multiple rows can exist for the same `run_id`.

**Two lookup modes:**

| Mode | When | How | What it returns |
|---|---|---|---|
| **Latest** | `last_updated_time` not provided | `query` with `ScanIndexForward=False, Limit=1` | Newest row for this `run_id` |
| **Exact** | `last_updated_time` provided | `get_item` with full composite key | That specific historical row |

**Latest mode** is the normal case — "give me the current state of this run."

**Exact mode** is for restarts — the Step Function re-runs a job from a
known historical point by passing the exact `last_updated_time`.

### 4. Extract job_id and job_type from the run

```python
job_id = job_run.get("job_id")      # e.g. "client"
job_type = job_run.get("job_type")  # e.g. "sourcing"
```

If either is missing → log error, write FAILED, raise exception.

These two values are the keys to look up the job's configuration.

### 5. Fetch job configuration (Step 2)

Query the `app-jobConfig` DynamoDB table using `job_id` + `job_type`.

**Table schema:**
- PK: `job_id` (string)
- SK: `job_type` (string)

Simple `get_item` — one row per (job_id, job_type) combination.

The job config contains everything about HOW the job runs:
- `job_runner` — what type of compute to use (ECS Fargate, Databricks)
- `pre_steps` — what processing to do before running
- `job_param` — data source, batch settings, API details
- `next_jobs` — what jobs to trigger after this one completes

**This function is schema-agnostic** — any new fields added to the
`app-jobConfig` table flow through automatically. No code changes needed.

### 6. Merge and return

```python
output = {**job_run, "job_config": job_config}
```

All job_run fields are spread at the top level. The entire job_config row
is nested under a `job_config` key.

### 7. Log success and write to logs table

```python
write_log(run_id=run_id, job_id=job_id, stage="GetConfig", status="SUCCESS")
return output
```

---

## The Output Shape

```json
{
    "run_id": "run-001",
    "last_updated_time": "2024-06-01T00:00:00Z",
    "job_id": "client",
    "job_type": "sourcing",
    "status": "WAITING",
    "trigger_type": "SCHEDULER",
    "start_time": "",
    "end_time": "",
    "next_scheduled_run_time": "",
    "last_heartbeat_time": "",
    "expiry_time": "",
    "mark_for_delete": false,
    "custom_attributes": {},
    "error": "",
    "delete_at": 0,

    "job_config": {
        "enabled": true,
        "trigger_type": "SCHEDULER",
        "run_frequency_in_mins": 60,
        "concurrent_runs_enabled": false,
        "job_runner": {
            "type": "ECS_Fargate",
            "name": "S2S3",
            "config": {
                "cluster": "my-ecs-cluster",
                "subnets": ["subnet-aaa111", "subnet-bbb222"],
                "security_groups": ["sg-abc123"],
                "task_definition": "default-task-def",
                "container_name": "default-container",
                "instance_size": "small",
                "image": ""
            }
        },
        "pre_steps": [
            { "pre_step_type": "change_since_append" },
            { "pre_step_type": "ddb_config_pull", "tables": ["service_config", "table_config"] }
        ],
        "job_param": {
            "source": {
                "type": "API",
                "name": "RDI",
                "url": "https://refdata-common.jpmchase.net/common/v2/countrygroup?data.schemaVersion=1",
                "file_type": "XML"
            },
            "batch_size": 1000,
            "thread_count": 10
        },
        "next_jobs": [
            { "type": "silver_load", "id": "dbr_client" }
        ],
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z"
    }
}
```

Since GetConfig has **no ResultPath** in the Step Function definition,
this output **replaces the entire Step Function payload**. Everything
downstream reads from this structure.

---

## The Code

### handler.py

```python
def lambda_handler(event, context):
    run_id = event.get("run_id") or "<missing>"
    job_id = "<unknown>"

    try:
        # Validate
        if run_id == "<missing>":
            raise ValueError("Missing required input: 'run_id'")

        last_updated_time = event.get("last_updated_time")

        dynamodb = get_dynamodb_resource()

        # Step 1: Get job run metadata
        job_run_table = dynamodb.Table(JOB_RUN_TABLE)       # "app-jobRun"
        job_run = get_job_run(job_run_table, run_id, last_updated_time)

        # Extract keys for config lookup
        job_id = job_run.get("job_id") or "<unknown>"
        job_type = job_run.get("job_type")

        if job_id == "<unknown>" or not job_type:
            raise ValueError("job_run record is missing 'job_id' or 'job_type'")

        # Step 2: Get job configuration
        job_config_table = dynamodb.Table(JOB_CONFIG_TABLE)  # "app-jobConfig"
        job_config = get_job_config(job_config_table, job_id, job_type)

        # Merge and return
        output = {**job_run, "job_config": job_config}

        write_log(run_id=run_id, job_id=job_id, stage="GetConfig", status="SUCCESS")
        return output

    except Exception as e:
        log.error("HANDLER_FAILED", {
            "run_id": run_id, "job_id": job_id,
            "error_type": type(e).__name__, "error_message": str(e),
        })
        write_log(run_id=run_id, job_id=job_id, stage="GetConfig", status="FAILED")
        raise
```

### dynamodb_ops.py — get_job_run

```python
def get_job_run(table, run_id, last_updated_time=None):
    if last_updated_time:
        # Exact fetch — full composite key (for restarts)
        response = table.get_item(Key={
            "run_id": run_id,
            "last_updated_time": last_updated_time,
        })
        if "Item" not in response:
            raise ValueError(f"No job_run found for run_id: {run_id}, "
                             f"last_updated_time: {last_updated_time}")
        return response["Item"]
    else:
        # Latest fetch — query newest row (normal case)
        response = table.query(
            KeyConditionExpression=Key("run_id").eq(run_id),
            ScanIndexForward=False,     # newest first
            Limit=1,                    # only need one
        )
        items = response.get("Items", [])
        if not items:
            raise ValueError(f"No job_run found for run_id: {run_id}")
        return items[0]
```

### dynamodb_ops.py — get_job_config

```python
def get_job_config(table, job_id, job_type):
    response = table.get_item(Key={"job_id": job_id, "job_type": job_type})

    if "Item" not in response:
        raise ValueError(f"No job_config found for job_id: {job_id}, "
                         f"job_type: {job_type}")
    return response["Item"]
```

---

## Why Limit=1 Is Safe Here (But Not in change_since_append)

In `get_job_run`, we use `Limit=1` because there's **no FilterExpression**.
The query returns rows sorted by `last_updated_time` descending, and we
want the first one. DynamoDB applies `Limit` to the key-matched rows
directly — no post-filtering that could cause missed results.

In `change_since_append`, we can't use `Limit=1` because there IS a
`FilterExpression` (job_type + status). DynamoDB would apply `Limit` first,
return one row, then filter it — potentially discarding the only result.

---

## Error Handling

Every error follows the same pattern:

1. **Log the error** — `log.error(...)` with structured details
2. **Write FAILED to logs table** — `write_log(..., status="FAILED")`
3. **Re-raise the exception** — Step Functions catches it via
   `Catch: States.ALL` and routes to `HandleError`

| Error | When | error_type |
|---|---|---|
| Missing `run_id` | Event has no run_id, or it's empty/null | `ValueError` |
| Run not found | No rows in `app-jobRun` for this run_id | `ValueError` |
| Exact fetch not found | run_id + last_updated_time combo doesn't exist | `ValueError` |
| Missing job_id/job_type | job_run row doesn't have these fields | `ValueError` |
| Config not found | No row in `app-jobConfig` for this job_id + job_type | `ValueError` |
| DynamoDB error | Throttling, permissions, network | `ClientError` |

### What run_id and job_id look like in FAILED logs

The handler extracts `run_id` and `job_id` early so they're available
in the `except` block. If the error happens before we can read them:

| When error happens | run_id in log | job_id in log |
|---|---|---|
| Before reading run_id | `"<missing>"` | `"<unknown>"` |
| After reading run_id, before job_run query | `"run-001"` | `"<unknown>"` |
| After job_run query, before job_config query | `"run-001"` | `"client"` |
| After job_config query (unlikely) | `"run-001"` | `"client"` |

This means you can always trace a FAILED log back to at least a run_id
(if one was provided).

---

## DynamoDB Tables Used

| Table | PK | SK | Read/Write | Purpose |
|---|---|---|---|---|
| `app-jobRun` | `run_id` | `last_updated_time` | **Read** | Job run metadata (status, timestamps) |
| `app-jobConfig` | `job_id` | `job_type` | **Read** | Job configuration (runner, params, steps) |
| `app-jobLog` | `run_id` | `time` | **Write** | Audit log (SUCCESS/FAILED per stage) |

Table names are configurable via environment variables:
`JOB_RUN_TABLE`, `JOB_CONFIG_TABLE`, `LOGS_TABLE`.

---

## The Restart Feature

### Normal run (most common)

```json
{ "run_id": "run-001" }
```

The lambda queries `app-jobRun` for the **newest row** for run-001.
This gives the current state of the run.

### Restart from a specific point

```json
{ "run_id": "run-001", "last_updated_time": "2024-03-15T10:00:00Z" }
```

The lambda fetches the **exact row** matching both keys. This gives a
historical snapshot — the state the run was in at that specific timestamp.

### Why this matters

If a job failed at step 3 of 5, you might want to restart from step 2.
By passing the `last_updated_time` from before the failure, you get the
pre-failure state and the Step Function can re-execute from that point.

### How it works internally

```python
if last_updated_time:
    # Exact: get_item with both PK + SK
    table.get_item(Key={"run_id": run_id, "last_updated_time": last_updated_time})
else:
    # Latest: query newest row by SK descending
    table.query(
        KeyConditionExpression=Key("run_id").eq(run_id),
        ScanIndexForward=False,
        Limit=1,
    )
```

---

## Schema-Agnostic Design

`get_job_config` returns the **entire row** from `app-jobConfig` without
filtering any fields:

```python
return response["Item"]    # everything, as-is
```

This means:
- **New fields added to job_config** (like `pre_steps` was added in v2)
  flow through automatically
- **No code change needed** when the schema evolves
- **The handler doesn't need to know** what's inside job_config — it just
  passes it along

The same applies to `get_job_run` — all fields from the job_run row are
spread at the top level of the output.

---

## How This Feeds the Rest of the Step Function

```
GetConfig output
    ↓
    ├── $.run_id                              → used by every downstream state
    ├── $.job_id                              → used by every downstream state
    ├── $.job_config.job_runner.type           → read by RunnerTypeChoice
    ├── $.job_config.pre_steps                 → read by PreStepsProcessor
    ├── $.job_config.job_param                 → copied into pre_steps_result
    ├── $.job_config.job_runner.config         → read by TriggerEcsJob
    └── $.job_config.next_jobs                 → read by ScheduleNextJob
```

Every downstream state depends on GetConfig's output. If GetConfig fails,
the entire Step Function stops at HandleError.

---

## Helper Function: get_last_updated_time

A utility for **writing** to the job_run table (not used by GetConfig
itself, but available for other lambdas that write job_run rows).

```python
def get_last_updated_time(provided=None):
    if provided and provided != "":
        return provided                # use what the caller gave
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # auto-set
```

Ensures every job_run row has a valid `last_updated_time` (the sort key).
If the caller doesn't provide one, it auto-generates the current UTC
timestamp in ISO-8601 format.
