# change_since_append — Logic Explained

## What It Does

When `pre_step_type` is `"change_since_append"`, the PreStepsProcessor lambda
queries the `app-jobRun` DynamoDB table to find the **start_time of the most
recent COMPLETED run** for a given job. This timestamp tells the downstream
lambda "when was the last time this job finished successfully?"

---

## Step-by-Step Flow

### 1. Handler routes to the function

The handler sees `pre_step_type == "change_since_append"` and calls:

```python
handle_change_since_append(step, event)
```

### 2. Extract job_id and job_type from the event

```python
job_id = event.get("job_id")      # e.g. "client"
job_type = event.get("job_type")  # e.g. "sourcing"
```

These identify which job we're looking for.

### 3. Query the app-jobRun table via GSI-2

The function queries the `app-jobRun` table using the Global Secondary Index
called `jobIdQuery`:

| GSI-2 Setting | Value |
|---|---|
| Index name | `jobIdQuery` |
| Partition key (PK) | `job_id` |
| Sort key (SK) | `start_time` |
| Projection | ALL (returns all fields) |

**Query parameters:**
- **KeyCondition:** `job_id = "client"` (match the job)
- **FilterExpression:** `job_type = "sourcing"` AND `status = "COMPLETED"` (only completed runs of this type)
- **ScanIndexForward:** `False` (sort newest `start_time` first)
- **No Limit** (because DynamoDB applies Limit before FilterExpression — using Limit=1 could miss valid rows)

### 4. Return the result

The function takes the first matching row's `start_time` and returns it.
If no rows match, it returns `null`.

---

## Three Possible Outcomes

| Scenario | What's in the table | Result |
|---|---|---|
| Prior completed run exists | Rows with `status=COMPLETED` for this `job_id`/`job_type` | `{"last_successful_start_time": "2024-05-15T08:30:00Z"}` |
| Runs exist but none COMPLETED | Only rows with `status=FAILED`, `RUNNING`, etc. | `{"last_successful_start_time": null}` |
| No runs at all for this job | No rows matching `job_id` in the index | `{"last_successful_start_time": null}` |

---

## Example

### DynamoDB rows in app-jobRun for job_id="client"

| run_id | job_id | job_type | status | start_time |
|---|---|---|---|---|
| run-001 | client | sourcing | COMPLETED | 2024-01-15T08:00:00Z |
| run-002 | client | sourcing | FAILED | 2024-03-01T09:00:00Z |
| run-003 | client | sourcing | COMPLETED | 2024-05-15T08:30:00Z |
| run-004 | client | sourcing | RUNNING | 2024-06-01T10:00:00Z |
| run-005 | client | other_type | COMPLETED | 2024-06-10T12:00:00Z |

**Query for `job_id=client`, `job_type=sourcing`, `status=COMPLETED`:**

- run-005 is excluded (wrong `job_type`)
- run-004 is excluded (status is RUNNING)
- run-002 is excluded (status is FAILED)
- run-003 matches ✅ (newest COMPLETED for this job_type)
- run-001 also matches but is older

**Result:** `{"last_successful_start_time": "2024-05-15T08:30:00Z"}`

---

## The Code

### step_handlers.py

```python
def handle_change_since_append(step, event):
    job_id = event.get("job_id")
    job_type = event.get("job_type")

    dynamodb = get_dynamodb_resource()
    table = dynamodb.Table(JOB_RUN_TABLE)        # "app-jobRun"

    start_time = get_last_successful_run_start_time(
        table=table, job_id=job_id, job_type=job_type,
    )

    return {"last_successful_start_time": start_time}   # string or None
```

### dynamodb_ops.py

```python
def get_last_successful_run_start_time(table, job_id, job_type):
    response = table.query(
        IndexName="jobIdQuery",                          # GSI-2
        KeyConditionExpression=Key("job_id").eq(job_id),
        FilterExpression=(
            Attr("job_type").eq(job_type)
            & Attr("status").eq("COMPLETED")             # only COMPLETED runs
        ),
        ScanIndexForward=False,                          # newest start_time first
    )

    items = response.get("Items", [])
    if not items:
        return None                                      # no completed run found

    return items[0].get("start_time")                    # e.g. "2024-05-15T08:30:00Z"
```

---

## Where the Result Ends Up

The handler collects the return and puts it under `results["change_since_append"]`:

```python
results[step["pre_step_type"]] = result
# results["change_since_append"] = {"last_successful_start_time": "2024-05-15T08:30:00Z"}
```

The final lambda output (which Step Functions nests under `$.pre_steps_result`):

```json
{
    "job_param": { "...": "copied from input as-is" },
    "change_since_append": {
        "last_successful_start_time": "2024-05-15T08:30:00Z"
    },
    "ddb_config_pull": { "...": "..." }
}
```

---

## Purpose — Why This Matters

The timestamp answers: **"When was the last time this job completed successfully?"**

The downstream lambda (e.g. TriggerEcsJob) can use this to:
- Append `&changedSince=2024-05-15T08:30:00Z` to an API URL
- Only fetch records that changed since the last run
- Skip re-processing data that was already handled

**But PreStepsProcessor doesn't do any of that.** It just provides the
timestamp. The downstream lambda decides how to use it. This keeps
PreStepsProcessor simple and the downstream lambda flexible.

---

## Why No Limit=1 on the Query

DynamoDB applies `Limit` **before** `FilterExpression`. So `Limit=1` would:

1. Return the single newest row by `start_time` (regardless of status/job_type)
2. THEN apply the filter
3. If that one row didn't match (e.g. it was FAILED), return empty — even though older COMPLETED rows exist

By not using `Limit`, we let DynamoDB scan through all rows for this `job_id`
and filter correctly. The first match in the filtered results is the newest
COMPLETED run.

---

## Error Handling

| Error | What happens |
|---|---|
| DynamoDB `ClientError` (throttling, permissions) | Logged as error, re-raised. Handler catches it, writes FAILED to `app-jobLog`, re-raises to Step Functions. |
| No completed runs found | Returns `null` — not an error. Downstream lambda handles this gracefully. |
| GSI doesn't exist | DynamoDB throws `ResourceNotFoundException` — caught and re-raised like any ClientError. |
