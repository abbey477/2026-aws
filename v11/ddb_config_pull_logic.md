# ddb_config_pull — Logic Explained

## What It Does

When `pre_step_type` is `"ddb_config_pull"`, the PreStepsProcessor lambda
reads configuration data from one or more DynamoDB tables. Each table is
looked up using `job_id` and `job_type` as the key. The results are passed
to the downstream lambda so it has everything it needs at runtime.

---

## Step-by-Step Flow

### 1. Handler routes to the function

The handler sees `pre_step_type == "ddb_config_pull"` and calls:

```python
handle_ddb_config_pull(step, event)
```

### 2. Extract job_id, job_type, and tables

```python
job_id = event.get("job_id")        # e.g. "client" — from the event
job_type = event.get("job_type")    # e.g. "sourcing" — from the event
tables = step.get("tables")         # e.g. ["service_config", "table_config"] — from the step
```

Note the difference:
- `job_id` and `job_type` come from the **event** (top-level fields from GetConfig)
- `tables` comes from the **step item** (the pre_step definition inside job_config)

### 3. Check if there are tables to pull

If `tables` is missing, not a list, or empty:
- Log a warning
- Return `{}` (empty dict)
- Handler sees empty result and doesn't add `ddb_config_pull` to the output

### 4. Loop through each table name

For each table in the list:
- Skip if the name is empty or not a string (defensive check)
- Connect to that DynamoDB table
- Call `pull_config_from_table` to look up the row

### 5. Look up the row

```python
table.get_item(Key={"job_id": "client", "job_type": "sourcing"})
```

This assumes the config tables use a two-part key:
- PK: `job_id`
- SK: `job_type`

**Note:** These config tables are **not yet created**. The architect will
confirm the schema. If it changes, only `pull_config_from_table` needs
updating.

### 6. Handle the result

The row (or `null`) is added to the results dict, keyed by table name.

---

## Five Possible Outcomes Per Table

| Scenario | What happens | Result for that table |
|---|---|---|
| Table exists + row found | Returns the full row | `{"feature_flag": true, "region": "us-east-1"}` |
| Table exists + no matching row | Returns None | `null` |
| Table doesn't exist yet | Catches error, returns None | `null` |
| Permission denied | Re-raises → lambda fails | Lambda crashes → FAILED → HandleError |
| Throttled | Re-raises → lambda fails | Lambda crashes → FAILED → HandleError |

---

## Error Handling — Two Categories

### Recoverable (don't crash)

**`ResourceNotFoundException`** — the table doesn't exist in DynamoDB yet.

This is **expected** right now because the config tables haven't been created.
The function catches this specific error, logs a warning, and returns `null`.
The lambda continues processing other tables and other pre_steps normally.

```
[PreStepsProcessor] [PULL_CONFIG_TABLE_NOT_FOUND] table=service_config,
    message=Table does not exist yet — returning null
```

### Unrecoverable (crash)

**`AccessDeniedException`** — the Lambda doesn't have permission to read
the table. This is a **configuration problem** that needs human attention.

**Any other `ClientError`** — throttling, network issues, etc.

These errors are re-raised. The handler catches them, writes `FAILED` to
the `app-jobLog` table, and re-raises to Step Functions. The `Catch` block
routes to `HandleError`.

---

## Example

### Input (the pre_step item)

```json
{
    "pre_step_type": "ddb_config_pull",
    "tables": ["service_config", "table_config"]
}
```

### DynamoDB table: service_config

| job_id | job_type | feature_flag | region |
|---|---|---|---|
| client | sourcing | true | us-east-1 |
| client | reporting | false | eu-west-1 |

### DynamoDB table: table_config

(doesn't exist yet)

### What happens

1. **service_config** — `get_item(job_id=client, job_type=sourcing)` → row found ✅
2. **table_config** — `get_item(...)` → `ResourceNotFoundException` → returns `null`, logs warning

### Result

```json
{
    "service_config": {
        "job_id": "client",
        "job_type": "sourcing",
        "feature_flag": true,
        "region": "us-east-1"
    },
    "table_config": null
}
```

---

## The Code

### step_handlers.py

```python
def handle_ddb_config_pull(step, event):
    job_id = event.get("job_id")
    job_type = event.get("job_type")
    tables = step.get("tables")

    # Nothing to pull
    if not isinstance(tables, list) or len(tables) == 0:
        return {}

    dynamodb = get_dynamodb_resource()
    results = {}

    for table_name in tables:
        if not isinstance(table_name, str) or table_name == "":
            continue                       # skip bad entries

        table = dynamodb.Table(table_name)
        row = pull_config_from_table(
            table=table, table_name=table_name,
            job_id=job_id, job_type=job_type,
        )
        results[table_name] = row          # row dict or None

    return results
```

### dynamodb_ops.py

```python
def pull_config_from_table(table, table_name, job_id, job_type):
    try:
        response = table.get_item(Key={"job_id": job_id, "job_type": job_type})
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")

        # Table doesn't exist yet — not an error, just no data.
        if error_code == "ResourceNotFoundException":
            log.warn("PULL_CONFIG_TABLE_NOT_FOUND", {
                "table": table_name,
                "message": "Table does not exist yet — returning null",
            })
            return None

        # Any other error (permissions, throttling) — re-raise.
        log.error("PULL_CONFIG_ERROR", {
            "table": table_name, "error_message": str(e),
        })
        raise

    item = response.get("Item")
    if item is None:
        return None       # table exists but no matching row

    return item           # full row as dict
```

---

## Where the Result Ends Up

The handler puts it under `results["ddb_config_pull"]`:

```python
results[step["pre_step_type"]] = result
# results["ddb_config_pull"] = {"service_config": {...}, "table_config": null}
```

Final lambda output:

```json
{
    "job_param": { "...": "copied from input as-is" },
    "change_since_append": {
        "last_successful_start_time": "2024-05-15T08:30:00Z"
    },
    "ddb_config_pull": {
        "service_config": {
            "job_id": "client",
            "job_type": "sourcing",
            "feature_flag": true,
            "region": "us-east-1"
        },
        "table_config": null
    }
}
```

Step Functions nests this under `$.pre_steps_result`. Downstream reads
`$.pre_steps_result.ddb_config_pull.service_config`.

---

## The Purpose

Config tables hold **per-job settings** that the downstream lambda (e.g.
TriggerEcsJob) needs at runtime. Instead of every lambda querying its own
config, PreStepsProcessor pulls it all once and passes it along.

Examples of what config tables might contain:
- Feature flags (enable/disable a processing step)
- Region-specific settings
- Connection strings or API endpoints
- Table mappings for data transformation

---

## Edge Cases Handled

| Edge case | What happens |
|---|---|
| `tables` key missing from step | Returns `{}` — logged as warning |
| `tables` is empty `[]` | Returns `{}` — logged as warning |
| A table name is empty string `""` | Skipped — logged as warning |
| A table name is not a string (e.g. `123`) | Skipped — logged as warning |
| Table doesn't exist in DynamoDB | Returns `null` — logged as warning |
| Table exists but no matching row | Returns `null` — logged as warning |
| Permission denied (`AccessDeniedException`) | Re-raised → lambda fails → HandleError |
| Throttled | Re-raised → lambda fails → HandleError |

---

## Future-Proof Design

The config tables (`service_config`, `table_config`) **don't exist yet**.
The code handles this gracefully:

- **Today:** Every table returns `null`. Lambda runs cleanly. No crashes.
- **Future (tables created):** Real data flows through automatically. Zero
  code changes needed. The `null` becomes `{...row data...}`.
- **If schema changes:** Only `pull_config_from_table` in `dynamodb_ops.py`
  needs updating (one function, one file).
