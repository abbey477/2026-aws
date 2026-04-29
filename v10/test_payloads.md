# Lambda Console Test Payloads

Test payloads for manual testing via the AWS Lambda console.
Copy-paste each JSON block into the "Test" tab of the Lambda console.

---

## Table of Contents

- [GetConfig Lambda](#getconfig-lambda)
  - [GC-1: Happy path — normal run](#gc-1-happy-path--normal-run)
  - [GC-2: Happy path — restart with last_updated_time](#gc-2-happy-path--restart-with-last_updated_time)
  - [GC-3: Missing run_id](#gc-3-missing-run_id)
  - [GC-4: Empty run_id](#gc-4-empty-run_id)
  - [GC-5: Nonexistent run_id](#gc-5-nonexistent-run_id)
  - [GC-6: Restart with nonexistent last_updated_time](#gc-6-restart-with-nonexistent-last_updated_time)
  - [GC-7: Empty event](#gc-7-empty-event)
  - [GC-8: Null run_id](#gc-8-null-run_id)
- [PreStepsProcessor Lambda](#prestepsprocessor-lambda)
  - [PSP-1: Happy path — both known pre_step_types](#psp-1-happy-path--both-known-pre_step_types)
  - [PSP-2: Only change_since_append](#psp-2-only-change_since_append)
  - [PSP-3: Only ddb_config_pull](#psp-3-only-ddb_config_pull)
  - [PSP-4: Empty pre_steps array](#psp-4-empty-pre_steps-array)
  - [PSP-5: No pre_steps key](#psp-5-no-pre_steps-key)
  - [PSP-6: No job_config key](#psp-6-no-job_config-key)
  - [PSP-7: pre_steps is null](#psp-7-pre_steps-is-null)
  - [PSP-8: Unknown pre_step_type](#psp-8-unknown-pre_step_type)
  - [PSP-9: Mix of known, unknown, and invalid items](#psp-9-mix-of-known-unknown-and-invalid-items)
  - [PSP-10: Invalid pre_step_type values](#psp-10-invalid-pre_step_type-values)
  - [PSP-11: ddb_config_pull with empty tables list](#psp-11-ddb_config_pull-with-empty-tables-list)
  - [PSP-12: ddb_config_pull with missing tables key](#psp-12-ddb_config_pull-with-missing-tables-key)
  - [PSP-13: Minimal event — just run_id](#psp-13-minimal-event--just-run_id)
  - [PSP-14: Duplicate pre_step_types](#psp-14-duplicate-pre_step_types)

---

# GetConfig Lambda

**AWS Lambda handler:** `get_config.handler.lambda_handler`

### GC-1: Happy path — normal run

Use a `run_id` that exists in your `app-jobRun` table. The lambda fetches the
latest row for that run_id and looks up its job_config.

```json
{
    "run_id": "run-001"
}
```

**Expected:** Returns merged payload with job_run fields at top level + job_config nested.

---

### GC-2: Happy path — restart with last_updated_time

Fetches a specific historical row instead of the latest. Use a `run_id` and
`last_updated_time` combination that exists in your `app-jobRun` table.

```json
{
    "run_id": "run-001",
    "last_updated_time": "2024-01-01T00:00:00Z"
}
```

**Expected:** Returns the exact row matching both keys, not the latest.

---

### GC-3: Missing run_id

No `run_id` in the event at all.

```json
{
    "some_other_field": "value"
}
```

**Expected:** ValueError — "Missing required input: 'run_id'". write_log called with FAILED.

---

### GC-4: Empty run_id

`run_id` is an empty string.

```json
{
    "run_id": ""
}
```

**Expected:** ValueError — "Missing required input: 'run_id'". write_log called with FAILED.

---

### GC-5: Nonexistent run_id

`run_id` that doesn't exist in the `app-jobRun` table.

```json
{
    "run_id": "this-run-does-not-exist-xyz"
}
```

**Expected:** ValueError — "No job_run found for run_id: ...". write_log called with FAILED.

---

### GC-6: Restart with nonexistent last_updated_time

Valid `run_id` but the specific `last_updated_time` doesn't exist.

```json
{
    "run_id": "run-001",
    "last_updated_time": "2099-12-31T23:59:59Z"
}
```

**Expected:** ValueError — "No job_run found for run_id: ..., last_updated_time: ...". write_log called with FAILED.

---

### GC-7: Empty event

Completely empty JSON.

```json
{}
```

**Expected:** ValueError — "Missing required input: 'run_id'". write_log called with FAILED.

---

### GC-8: Null run_id

`run_id` explicitly set to null.

```json
{
    "run_id": null
}
```

**Expected:** ValueError — "Missing required input: 'run_id'". write_log called with FAILED.

---

# PreStepsProcessor Lambda

**AWS Lambda handler:** `pre_steps_processor.handler.lambda_handler`

**Important:** These payloads simulate what GetConfig would send through the
Step Function. In production, PreStepsProcessor never receives events
directly — they come from GetConfig's output.

### PSP-1: Happy path — both known pre_step_types

Tests the full flow: change_since_append queries `app-jobRun` GSI-2 for the
last completed run, ddb_config_pull reads from config tables.

```json
{
    "run_id": "run-001",
    "job_id": "client",
    "job_type": "sourcing",
    "status": "WAITING",
    "trigger_type": "SCHEDULER",
    "last_updated_time": "2024-06-01T00:00:00Z",
    "custom_attributes": {},
    "job_config": {
        "enabled": true,
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
            {
                "pre_step_type": "ddb_config_pull",
                "tables": ["service_config", "table_config"]
            }
        ],
        "job_param": {
            "source": {
                "type": "API",
                "name": "RDI"
            },
            "batch_size": 1000,
            "thread_count": 10
        },
        "next_jobs": [
            { "type": "silver_load", "id": "dbr_client" }
        ]
    }
}
```

**Expected:** Returns dict with `change_since_append` (start_time or null) and `ddb_config_pull` (pulled rows or null per table). Requires `app-jobRun` table + GSI-2 and config tables to exist.

---

### PSP-2: Only change_since_append

Just the change_since_append step — no ddb_config_pull.

```json
{
    "run_id": "run-001",
    "job_id": "client",
    "job_type": "sourcing",
    "job_config": {
        "pre_steps": [
            { "pre_step_type": "change_since_append" }
        ]
    }
}
```

**Expected:** Returns `{"change_since_append": {"last_successful_start_time": "..." or null, "placeholder": true}}`.

---

### PSP-3: Only ddb_config_pull

Just the ddb_config_pull step — no change_since_append.

```json
{
    "run_id": "run-001",
    "job_id": "client",
    "job_type": "sourcing",
    "job_config": {
        "pre_steps": [
            {
                "pre_step_type": "ddb_config_pull",
                "tables": ["service_config", "table_config"]
            }
        ]
    }
}
```

**Expected:** Returns `{"ddb_config_pull": {"service_config": {...} or null, "table_config": {...} or null}}`. Requires config tables to exist.

---

### PSP-4: Empty pre_steps array

pre_steps exists but is empty — nothing to process.

```json
{
    "run_id": "run-002",
    "job_id": "client",
    "job_type": "sourcing",
    "job_config": {
        "pre_steps": []
    }
}
```

**Expected:** Returns `{}`. handle_no_pre_steps is called. write_log SUCCESS.

---

### PSP-5: No pre_steps key

job_config exists but doesn't contain pre_steps at all.

```json
{
    "run_id": "run-003",
    "job_id": "client",
    "job_type": "sourcing",
    "job_config": {
        "enabled": true,
        "job_runner": { "type": "ECS_Fargate" }
    }
}
```

**Expected:** Returns `{}`. handle_no_pre_steps is called. write_log SUCCESS.

---

### PSP-6: No job_config key

Event has no job_config at all — simulates a badly formed GetConfig output.

```json
{
    "run_id": "run-004",
    "job_id": "client",
    "job_type": "sourcing"
}
```

**Expected:** Returns `{}`. Should NOT crash. handle_no_pre_steps is called. write_log SUCCESS.

---

### PSP-7: pre_steps is null

Explicitly null instead of missing or empty.

```json
{
    "run_id": "run-005",
    "job_id": "client",
    "job_type": "sourcing",
    "job_config": {
        "pre_steps": null
    }
}
```

**Expected:** Returns `{}`. handle_no_pre_steps is called. write_log SUCCESS.

---

### PSP-8: Unknown pre_step_type

A pre_step_type value we don't have a handler for.

```json
{
    "run_id": "run-006",
    "job_id": "client",
    "job_type": "sourcing",
    "job_config": {
        "pre_steps": [
            { "pre_step_type": "something_we_dont_handle" }
        ]
    }
}
```

**Expected:** Returns `{}`. Unknown type is logged as a warning but doesn't cause an error. write_log SUCCESS.

---

### PSP-9: Mix of known, unknown, and invalid items

Tests the router's ability to handle a messy array.

```json
{
    "run_id": "run-007",
    "job_id": "client",
    "job_type": "sourcing",
    "job_config": {
        "pre_steps": [
            { "pre_step_type": "change_since_append" },
            { "pre_step_type": "mystery_type" },
            {},
            { "pre_step_type": "" },
            "not-a-dict",
            null,
            {
                "pre_step_type": "ddb_config_pull",
                "tables": ["service_config"]
            }
        ]
    }
}
```

**Expected:** change_since_append and ddb_config_pull are processed. mystery_type routes to unknown handler. Empty/invalid items are skipped. write_log SUCCESS.

---

### PSP-10: Invalid pre_step_type values

Every item has a pre_step_type that's invalid in a different way.

```json
{
    "run_id": "run-008",
    "job_id": "client",
    "job_type": "sourcing",
    "job_config": {
        "pre_steps": [
            { "pre_step_type": null },
            { "pre_step_type": "" },
            { "pre_step_type": 123 },
            { "pre_step_type": true },
            { "wrong_key": "change_since_append" }
        ]
    }
}
```

**Expected:** Returns `{}`. All items are invalid — none have a valid string pre_step_type. handle_no_pre_steps is called. write_log SUCCESS.

---

### PSP-11: ddb_config_pull with empty tables list

The step exists but has no tables to pull.

```json
{
    "run_id": "run-009",
    "job_id": "client",
    "job_type": "sourcing",
    "job_config": {
        "pre_steps": [
            {
                "pre_step_type": "ddb_config_pull",
                "tables": []
            }
        ]
    }
}
```

**Expected:** Returns `{}`. ddb_config_pull handler runs but returns empty (no tables to pull). write_log SUCCESS.

---

### PSP-12: ddb_config_pull with missing tables key

The step has the right type but forgot to include `tables`.

```json
{
    "run_id": "run-010",
    "job_id": "client",
    "job_type": "sourcing",
    "job_config": {
        "pre_steps": [
            { "pre_step_type": "ddb_config_pull" }
        ]
    }
}
```

**Expected:** Returns `{}`. ddb_config_pull handler handles missing `tables` gracefully. write_log SUCCESS.

---

### PSP-13: Minimal event — just run_id

Bare minimum event with no job_config structure.

```json
{
    "run_id": "run-011"
}
```

**Expected:** Returns `{}`. No job_config → no pre_steps → handle_no_pre_steps. job_id defaults to `<unknown>` in write_log. write_log SUCCESS.

---

### PSP-14: Duplicate pre_step_types

Same pre_step_type appears twice. Tests whether the second result overwrites the first.

```json
{
    "run_id": "run-012",
    "job_id": "client",
    "job_type": "sourcing",
    "job_config": {
        "pre_steps": [
            { "pre_step_type": "change_since_append" },
            { "pre_step_type": "change_since_append" }
        ]
    }
}
```

**Expected:** Both run. The second result overwrites the first in the return dict (both keyed as `change_since_append`). write_log SUCCESS.

---

## Quick reference — expected outcomes

### GetConfig

| Test | Outcome | write_log status |
|---|---|---|
| GC-1 | ✅ Success — merged payload | SUCCESS |
| GC-2 | ✅ Success — exact historical row | SUCCESS |
| GC-3 | ❌ ValueError | FAILED |
| GC-4 | ❌ ValueError | FAILED |
| GC-5 | ❌ ValueError | FAILED |
| GC-6 | ❌ ValueError | FAILED |
| GC-7 | ❌ ValueError | FAILED |
| GC-8 | ❌ ValueError | FAILED |

### PreStepsProcessor

| Test | Outcome | write_log status |
|---|---|---|
| PSP-1 | ✅ Both steps processed | SUCCESS |
| PSP-2 | ✅ change_since_append only | SUCCESS |
| PSP-3 | ✅ ddb_config_pull only | SUCCESS |
| PSP-4 | ✅ Empty result `{}` | SUCCESS |
| PSP-5 | ✅ Empty result `{}` | SUCCESS |
| PSP-6 | ✅ Empty result `{}` | SUCCESS |
| PSP-7 | ✅ Empty result `{}` | SUCCESS |
| PSP-8 | ✅ Empty result `{}` | SUCCESS |
| PSP-9 | ✅ Known steps processed, rest skipped/warned | SUCCESS |
| PSP-10 | ✅ Empty result `{}` | SUCCESS |
| PSP-11 | ✅ Empty result `{}` | SUCCESS |
| PSP-12 | ✅ Empty result `{}` | SUCCESS |
| PSP-13 | ✅ Empty result `{}` | SUCCESS |
| PSP-14 | ✅ Second overwrites first | SUCCESS |

---

## Notes

- **GC tests that return errors:** In the Lambda console you'll see a stack
  trace — this is normal. In Step Functions, the Catch block intercepts
  these and routes to HandleError cleanly.
- **PSP tests that hit DynamoDB:** PSP-1, PSP-2, PSP-3, and PSP-9 actually
  query real tables. Make sure the Lambda has IAM permissions to read
  `app-jobRun` (+ GSI-2 jobIdQuery), `service_config`, `table_config`,
  and write to `app-jobLog`.
- **PSP tests that don't hit DynamoDB:** PSP-4 through PSP-8, PSP-10
  through PSP-14 only exercise routing logic — no real DynamoDB calls.
