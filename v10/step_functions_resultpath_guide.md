# Step Functions ResultPath — How It Controls What the Next State Receives

A practical guide with concrete examples showing how `ResultPath` affects
the JSON payload that flows between states in an AWS Step Function.

---

## Table of Contents

- [Setup — Same for All Examples](#setup--same-for-all-examples)
- [Option 1 — ResultPath: "$.pre_steps_result"](#option-1--resultpath-pre_steps_result)
- [Option 2 — ResultPath: "$"](#option-2--resultpath-)
- [Option 3 — No ResultPath Set](#option-3--no-resultpath-set)
- [Option 4 — ResultPath: "$.any.nested.path"](#option-4--resultpath-anynested-path)
- [Option 5 — ResultPath: null](#option-5--resultpath-null)
- [Summary Table](#summary-table)
- [Which Should You Use?](#which-should-you-use)
- [Real-World Example — Our Step Function](#real-world-example--our-step-function)

---

## Setup — Same for All Examples

For every example below, we use the same input and the same Lambda return.
Only `ResultPath` changes — and that one setting completely changes what the
next state sees.

### Payload coming INTO the Lambda state (from the previous state):

```json
{
    "run_id": "run-001",
    "job_id": "client",
    "job_config": {
        "job_runner": { "type": "ECS_Fargate" }
    }
}
```

### What the Lambda returns:

```json
{
    "change_since_append": {
        "last_successful_start_time": "2024-05-15T08:30:00Z"
    }
}
```

Now let's see what the **next state receives** with each ResultPath option.

---

## Option 1 — ResultPath: "$.pre_steps_result"

### What it means

> "Keep the original input untouched. Take whatever the Lambda returned
> and slot it into a key called `pre_steps_result`."

### Step Function definition

```json
{
    "Type": "Task",
    "Resource": "arn:aws:lambda:...",
    "ResultPath": "$.pre_steps_result",
    "Next": "RunnerTypeChoice"
}
```

### What the next state receives

```json
{
    "run_id": "run-001",
    "job_id": "client",
    "job_config": {
        "job_runner": { "type": "ECS_Fargate" }
    },
    "pre_steps_result": {
        "change_since_append": {
            "last_successful_start_time": "2024-05-15T08:30:00Z"
        }
    }
}
```

### How to access things from the next state

| Path | Value |
|---|---|
| `$.run_id` | `"run-001"` ✅ still there |
| `$.job_config.job_runner.type` | `"ECS_Fargate"` ✅ still there |
| `$.pre_steps_result.change_since_append.last_successful_start_time` | `"2024-05-15..."` ✅ new data |

### Pros

- Original input is preserved — nothing lost
- Lambda only needs to return new data — simple code
- Clean separation: original data vs. enrichment data

### Cons

- Downstream states must know to look inside `$.pre_steps_result.*`
- Slightly longer JSONPath expressions

---

## Option 2 — ResultPath: "$"

### What it means

> "Throw away the original input entirely. Replace the whole payload with
> whatever the Lambda returned."

### Step Function definition

```json
{
    "Type": "Task",
    "Resource": "arn:aws:lambda:...",
    "ResultPath": "$",
    "Next": "RunnerTypeChoice"
}
```

### What the next state receives

```json
{
    "change_since_append": {
        "last_successful_start_time": "2024-05-15T08:30:00Z"
    }
}
```

### How to access things from the next state

| Path | Value |
|---|---|
| `$.run_id` | ❌ **GONE** — not in the payload anymore |
| `$.job_config.job_runner.type` | ❌ **GONE** |
| `$.change_since_append.last_successful_start_time` | `"2024-05-15..."` ✅ |

### The problem

The original input (`run_id`, `job_config`, etc.) is lost. If the next state
needs those fields (like `RunnerTypeChoice` reading `$.job_config.job_runner.type`),
the Step Function will fail.

### The fix — Lambda must return everything

If you use `ResultPath: "$"`, your Lambda must include the original input in
its return value:

```python
# Lambda code
return {
    **event,                          # spread the original input
    "change_since_append": { ... },   # add new data
}
```

Then the next state receives:

```json
{
    "run_id": "run-001",
    "job_id": "client",
    "job_config": {
        "job_runner": { "type": "ECS_Fargate" }
    },
    "change_since_append": {
        "last_successful_start_time": "2024-05-15T08:30:00Z"
    }
}
```

Everything is flat at the top level. No `pre_steps_result` wrapper.

### Pros

- Simpler JSONPath — everything is at the top level
- Lambda has full control over the output shape

### Cons

- Lambda code is more complex — must spread the input back out
- Risk of accidentally dropping or overwriting input fields
- Larger return payload (duplicates the input)

---

## Option 3 — No ResultPath Set

### What it means

> Identical to `ResultPath: "$"`. When you don't set ResultPath at all,
> Step Functions defaults to replacing the entire payload.

This is what **GetConfig** uses in our Step Function — it returns the full
merged payload and replaces whatever the Step Function started with.

---

## Option 4 — ResultPath: "$.any.nested.path"

### What it means

> "Keep the original input. Put the Lambda's return at this nested path."

You can nest as deep as you want.

### Step Function definition

```json
{
    "Type": "Task",
    "Resource": "arn:aws:lambda:...",
    "ResultPath": "$.enrichment.pre_flight",
    "Next": "RunnerTypeChoice"
}
```

### What the next state receives

```json
{
    "run_id": "run-001",
    "job_id": "client",
    "job_config": {
        "job_runner": { "type": "ECS_Fargate" }
    },
    "enrichment": {
        "pre_flight": {
            "change_since_append": {
                "last_successful_start_time": "2024-05-15T08:30:00Z"
            }
        }
    }
}
```

### How to access things

| Path | Value |
|---|---|
| `$.run_id` | `"run-001"` ✅ |
| `$.job_config.job_runner.type` | `"ECS_Fargate"` ✅ |
| `$.enrichment.pre_flight.change_since_append.last_successful_start_time` | `"2024-05-15..."` ✅ |

### Pros

- Can organise results hierarchically
- Original input preserved

### Cons

- Long JSONPath expressions
- Deeper nesting = harder to read

---

## Option 5 — ResultPath: null

### What it means

> "Throw away whatever the Lambda returned. Pass the original input
> through to the next state completely unchanged."

### Step Function definition

```json
{
    "Type": "Task",
    "Resource": "arn:aws:lambda:...",
    "ResultPath": null,
    "Next": "NextState"
}
```

### What the next state receives

```json
{
    "run_id": "run-001",
    "job_id": "client",
    "job_config": {
        "job_runner": { "type": "ECS_Fargate" }
    }
}
```

The Lambda's return value is **completely discarded**. The payload passes
through as if the Lambda never ran.

### When to use this

Useful for Lambdas that only do **side effects** — things like:
- Sending an email
- Writing a log entry
- Triggering a notification

Where you don't care about the return value, just that the Lambda ran
successfully.

### Pros

- Payload stays clean — no extra keys added
- Good for fire-and-forget tasks

### Cons

- Lambda output is lost — nothing can be read downstream
- If the Lambda produced useful data, it's gone

---

## Summary Table

| ResultPath | Input preserved? | Lambda return goes where? | Risk |
|---|---|---|---|
| `"$.pre_steps_result"` | ✅ Yes | Nested at that key | None — safest |
| `"$"` | ❌ No — replaced | Replaces entire payload | Lambda must return everything |
| *(not set)* | ❌ No — replaced | Same as `"$"` | Same risk as above |
| `"$.any.path"` | ✅ Yes | Nested at that path | None |
| `null` | ✅ Yes | Thrown away | Lambda output lost |

---

## Which Should You Use?

### For Lambdas that ENRICH the payload (add new data):

**Use `ResultPath: "$.some_key"`** — keeps the original input, adds your
Lambda's data at a known location. This is the safest and most predictable
option.

### For Lambdas that REPLACE the payload (build a new output):

**Use `ResultPath: "$"` (or don't set it)** — gives the Lambda full control
over the output shape. The Lambda must include any input fields that
downstream states need.

### For Lambdas that are fire-and-forget (side effects only):

**Use `ResultPath: null`** — payload passes through untouched.

---

## Real-World Example — Our Step Function

Here's how our Step Function uses different ResultPath settings:

### GetConfig — No ResultPath (same as "$")

```json
"GetConfig": {
    "Type": "Task",
    "Resource": "arn:aws:lambda:...get-config",
    "Next": "PreStepsProcessor"
}
```

- **Why:** GetConfig builds the entire payload from scratch (merges job_run +
  job_config). There's no previous input to preserve — the Step Function just
  started.
- **Lambda returns:** The full merged payload
- **Next state sees:** Exactly what the Lambda returned

### PreStepsProcessor — ResultPath: "$.pre_steps_result"

```json
"PreStepsProcessor": {
    "Type": "Task",
    "Resource": "arn:aws:lambda:...pre-steps-processor",
    "ResultPath": "$.pre_steps_result",
    "Next": "RunnerTypeChoice"
}
```

- **Why:** PreStepsProcessor enriches the payload — it adds new data but
  doesn't want to lose the original input (run_id, job_config, etc.).
- **Lambda returns:** Only the new data (step results)
- **Next state sees:** Original input + Lambda return nested at `$.pre_steps_result`

### TriggerEcsJob — ResultPath: "$.trigger_result"

```json
"TriggerEcsJob": {
    "Type": "Task",
    "Resource": "arn:aws:lambda:...ecs-fargate-trigger",
    "ResultPath": "$.trigger_result",
    "Next": "CheckTriggerStatus"
}
```

- **Why:** Same pattern — enrich, don't replace. The trigger result is added
  alongside the existing payload.
- **Lambda returns:** Trigger status and metadata
- **Next state sees:** Everything from before + `$.trigger_result`

### The pattern

```
Start
  ↓
GetConfig         ResultPath: "$"                 → builds the payload
  ↓
PreStepsProcessor ResultPath: "$.pre_steps_result" → adds enrichment
  ↓
RunnerTypeChoice  (Choice — no Lambda, no ResultPath)
  ↓
TriggerEcsJob     ResultPath: "$.trigger_result"   → adds trigger info
  ↓
... and so on — each Lambda adds its piece without losing what came before
```

Each state is like adding a new chapter to a book. The book (payload) keeps
growing, and every previous chapter is still there for any future state to
read.

---

## Key Takeaway

**You almost never need your Lambda to return the original input.** If you
use `ResultPath: "$.some_key"`, Step Functions preserves the input for you.
Your Lambda just returns the new stuff, and Step Functions merges it in.

The only time you need `ResultPath: "$"` is when you're **building the
payload from scratch** (like GetConfig at the start of the pipeline) or
when you need to **modify existing fields** (which Step Functions can't do
with ResultPath alone — the Lambda must return the full modified payload).
