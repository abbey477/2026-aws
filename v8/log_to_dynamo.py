"""
Shared DynamoDB log writer for all Lambda functions.

Writes structured log entries to the 'logs' DynamoDB table.

Table Schema:
    PK : run_id    (string)  – partition key
    SK : time      (string)  – ISO 8601 timestamp (sort key)
    job_id  (string)
    stage   (string) – lambda/stage name
    status  (string) – e.g. STARTED, SUCCESS, FAILED
    delete_at (number) – TTL epoch (30 days from now)
"""

import os
import logging
from datetime import datetime, timedelta, timezone

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

LOGS_TABLE = os.environ.get("LOGS_TABLE", "logs")

_dynamodb_resource = None


def _get_dynamodb_resource():
    """Lazy-initialise and return a DynamoDB resource (re-usable across warm starts)."""
    global _dynamodb_resource
    if _dynamodb_resource is None:
        _dynamodb_resource = boto3.resource("dynamodb")
    return _dynamodb_resource


def set_dynamodb_resource(resource):
    """Allow tests to inject a mock DynamoDB resource."""
    global _dynamodb_resource
    _dynamodb_resource = resource


def write_log(
    run_id: str,
    job_id: str,
    stage: str,
    status: str,
) -> None:
    """
    Write a log entry to the logs DynamoDB table.

    Args:
        run_id:  The unique run identifier (partition key).
        job_id:  The job identifier.
        stage:   The lambda / pipeline stage name
                 (e.g. GetConfig, TriggerEcsJob, CheckJobStatus …).
        status:  The status to record
                 (e.g. STARTED, SUCCESS, FAILED, RUNNING …).
    """
    now = datetime.now(timezone.utc)
    time_iso = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    delete_at = int((now + timedelta(days=30)).timestamp())

    item = {
        "run_id": run_id,
        "time": time_iso,
        "job_id": job_id,
        "stage": stage,
        "status": status,
        "delete_at": delete_at,
    }

    try:
        dynamodb = _get_dynamodb_resource()
        table = dynamodb.Table(LOGS_TABLE)
        table.put_item(Item=item)
        logger.info(
            f"[LogToDynamo] run_id={run_id}, stage={stage}, status={status}, time={time_iso}"
        )
    except Exception as exc:
        # Logging should never break the pipeline – swallow and warn.
        logger.warning(
            f"[LogToDynamo] FAILED to write log: {exc} | "
            f"run_id={run_id}, stage={stage}, status={status}"
        )
