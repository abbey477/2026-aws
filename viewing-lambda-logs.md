# Viewing Logs from Your Python Lambda

A beginner's guide to seeing what your Lambda function logs when you run it from the AWS console.


&nbsp;

═══════════════════════════════════════════════════════════════

## 1. The Short Answer

═══════════════════════════════════════════════════════════════

&nbsp;

When you click **Test** in the Lambda console, scroll down. There's a **Log output** section that shows everything your function logged. That's it for quick checks.

For more (full history, multiple runs, easier searching), use **CloudWatch Logs**.


&nbsp;

═══════════════════════════════════════════════════════════════

## 2. Background: How Logging Works in Lambda

═══════════════════════════════════════════════════════════════

&nbsp;

Every time your Lambda runs, AWS automatically captures anything you log and sends it to a service called **CloudWatch Logs**. You don't have to set this up — it's built in.

The logs are stored in a place called a **log group**, named:

```
/aws/lambda/<your-function-name>
```

So if your function is called `myFunction`, your logs live in `/aws/lambda/myFunction`.


&nbsp;

═══════════════════════════════════════════════════════════════

## 3. Writing Logs in Your Python Code

═══════════════════════════════════════════════════════════════

&nbsp;

Use Python's built-in `logging` module. It automatically adds timestamps, log levels, and the request ID to every line:

```python
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info("Function started")
    logger.info(f"Got event: {event}")
    
    try:
        result = 2 + 2
        logger.info(f"Result is {result}")
    except Exception as e:
        logger.error(f"Something went wrong: {e}")
    
    return {"statusCode": 200, "body": "done"}
```

### Log Levels

- `logger.info(...)` — for normal informational messages
- `logger.warning(...)` — for things that look suspicious but didn't break
- `logger.error(...)` — for actual errors
- `logger.debug(...)` — for very detailed messages (won't show unless you set the level to `DEBUG`)

### Beginner Gotcha

If you do `logger = logging.getLogger(__name__)` (with a name in the parentheses), Lambda's default settings might filter out your messages.

**Easiest fix:** use `logging.getLogger()` with no arguments, like the example above. That uses Lambda's pre-configured root logger.


&nbsp;

═══════════════════════════════════════════════════════════════

## 4. How to See Your Logs

═══════════════════════════════════════════════════════════════

&nbsp;

There are three main methods. Pick whichever fits your moment.


&nbsp;

---

### Method 1 — The Test Console (Quickest)

---

This is what you'll use most often when developing.

1. Open your Lambda function in the AWS Console
2. Click the **Test** tab (or **Test** button)
3. Set up a test event if you haven't already (any JSON works — even just `{}`)
4. Click the orange **Test** button
5. Wait a moment for it to run
6. Look for the **Execution result** box that appears
7. Click to expand **Details**
8. Scroll to the **Log output** section at the bottom

You'll see something like this:

```
START RequestId: abc123-def... Version: $LATEST
[INFO]  2026-04-26T15:30:00.123Z  abc123-def...  Function started
[INFO]  2026-04-26T15:30:00.124Z  abc123-def...  Got event: {}
[INFO]  2026-04-26T15:30:00.125Z  abc123-def...  Result is 4
END RequestId: abc123-def...
REPORT RequestId: abc123-def...  Duration: 5.23 ms  Billed Duration: 6 ms ...
```

> **Limitation:** This box only shows the **last 4 KB** of logs from this single run. If your function logs a lot, or you want to see previous runs, you need CloudWatch.


&nbsp;

---

### Method 2 — CloudWatch Logs (Full History)

---

This is where ALL your logs live, forever (or until you set them to expire).

**Quickest way to get there from your Lambda:**

1. In your Lambda function page, click the **Monitor** tab
2. Click **View CloudWatch logs** (a button near the top right)
3. You'll land in CloudWatch on your function's log group

**Or directly:**

1. Go to the **CloudWatch** service in the AWS Console
2. In the left sidebar, click **Log groups**
3. Find and click `/aws/lambda/<your-function-name>`

Once you're in the log group, you'll see a list of **log streams**. Each stream is roughly one Lambda container. Click the most recent one (top of the list) to see the latest logs.


&nbsp;

---

### Method 3 — Live Tailing from Your Terminal (Best for Active Development)

---

If you have the AWS CLI installed and configured, this is the nicest workflow:

```bash
aws logs tail /aws/lambda/your-function-name --follow
```

This streams logs to your terminal in real time. Click **Test** in the console, and the logs appear immediately in your terminal — no refreshing needed.

**Useful flags:**

```bash
# Cleaner formatting
aws logs tail /aws/lambda/your-function-name --follow --format short

# Only show logs from the last 10 minutes
aws logs tail /aws/lambda/your-function-name --since 10m

# Filter for specific text
aws logs tail /aws/lambda/your-function-name --filter-pattern "ERROR"
```

If you don't have the AWS CLI yet, you can install it from <https://aws.amazon.com/cli/> and run `aws configure` to set up your credentials.


&nbsp;

═══════════════════════════════════════════════════════════════

## 5. Searching Logs (CloudWatch Logs Insights)

═══════════════════════════════════════════════════════════════

&nbsp;

Once you have lots of logs, you'll want to search them. CloudWatch has a query tool for this.

1. In CloudWatch, click **Logs Insights** in the left sidebar
2. Pick your log group from the dropdown: `/aws/lambda/<your-function-name>`
3. Type a query and click **Run query**

A few useful queries to start with.

**Show all error messages from the last hour:**

```
fields @timestamp, @message
| filter @message like /ERROR/
| sort @timestamp desc
| limit 100
```

**Find all invocations that took over 1 second:**

```
fields @timestamp, @duration, @message
| filter @type = "REPORT" and @duration > 1000
| sort @duration desc
```

**Just dump everything recent:**

```
fields @timestamp, @message
| sort @timestamp desc
| limit 50
```

You don't need to memorize this — there are sample queries built into the page.


&nbsp;

═══════════════════════════════════════════════════════════════

## 6. Common Problems

═══════════════════════════════════════════════════════════════

&nbsp;

---

### Problem: "I don't see any logs at all"

---

Three things to check:

1. **Did the function actually run?** Check the **Execution result** at the top — did it succeed or fail before any of your code ran?

2. **Does your Lambda have permission to write logs?** Your Lambda needs an IAM role with the `AWSLambdaBasicExecutionRole` policy (or equivalent). Without it, logs silently disappear. To check:
   - Lambda console → your function → **Configuration** tab → **Permissions**
   - Click the role name (opens IAM)
   - Make sure `AWSLambdaBasicExecutionRole` is attached

3. **Is the log group even there?** The log group `/aws/lambda/<function-name>` is only created **after the first invocation**. If you've never successfully invoked, it won't exist yet.


&nbsp;

---

### Problem: "My `logger.info()` messages don't show up"

---

You probably did this:

```python
logger = logging.getLogger(__name__)   # ← named logger
logger.info("hello")  # might be filtered
```

Fix: either set the level explicitly, or use the root logger:

```python
# Option 1: set the level
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Option 2: use the root logger (simpler)
logger = logging.getLogger()
logger.setLevel(logging.INFO)
```


&nbsp;

---

### Problem: "I see logs but they're not from this run"

---

CloudWatch shows logs from many runs in many streams. To make sure you're looking at the latest:

- Sort log streams by **Last Event Time** (descending)
- Or use Logs Insights, which searches across all streams at once
- Or use the live tail method, which only shows new logs


&nbsp;

---

### Problem: "Tracebacks are cut off"

---

If your function crashes, Lambda logs the full traceback automatically — but the test console only shows the last 4 KB. If you need the full trace, head to CloudWatch.


&nbsp;

═══════════════════════════════════════════════════════════════

## 7. Recommended Workflow for Beginners

═══════════════════════════════════════════════════════════════

&nbsp;

**When you're just starting out:**

1. Use `logger.info()` liberally — log the input, log major steps, log the output
2. Click Test in the console and read the Log output box
3. When that's not enough, click through to CloudWatch for the full picture

**When you're more comfortable:**

1. Set up `aws logs tail` in a side terminal while you develop
2. Test from the console, watch logs scroll in your terminal
3. Use Logs Insights to search history when something went wrong yesterday


&nbsp;

═══════════════════════════════════════════════════════════════

## 8. Cheat Sheet

═══════════════════════════════════════════════════════════════

&nbsp;

| What I want | What to do |
|---|---|
| See logs from the test I just ran | Scroll down in the Test tab to **Log output** |
| See full history of all runs | CloudWatch → Log groups → `/aws/lambda/<n>` |
| Watch logs live as I test | `aws logs tail /aws/lambda/<n> --follow` |
| Search across all logs | CloudWatch → Logs Insights |
| Fix "no logs appearing" | Check IAM role has `AWSLambdaBasicExecutionRole` |
| Log a message | `logger.info("message")` |


&nbsp;

═══════════════════════════════════════════════════════════════

## 9. A Minimal Example to Try

═══════════════════════════════════════════════════════════════

&nbsp;

Paste this into your Lambda, save, and click Test. You'll see clear log output.

```python
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info("=== Function starting ===")
    logger.info(f"Event received: {event}")
    logger.info(f"Function name: {context.function_name}")
    logger.info(f"Request ID: {context.aws_request_id}")
    
    name = event.get("name", "world")
    message = f"Hello, {name}!"
    
    logger.info(f"Returning message: {message}")
    logger.info("=== Function finished ===")
    
    return {
        "statusCode": 200,
        "body": message
    }
```

Try a test event like `{"name": "Alice"}` and see how each log line appears in order.
