"""
ParamStore — writes job_param to DynamoDB so the container can fetch it.

Fargate RunTask overrides are capped at 8KB total, which is too small
for many job_param payloads. We write the payload to DynamoDB and pass
only the run_id as an env var to the container.
"""

import json
import logging
import time
from typing import Any, Optional

import boto3
from mypy_boto3_dynamodb.client import DynamoDBClient

logger: logging.Logger = logging.getLogger(__name__)

PARAM_TTL_SECONDS: int = 7 * 24 * 60 * 60  # 7 days


class ParamStore:
    """
    Writes job_param as JSON to a DynamoDB table.

    Table schema:
      - Partition key: run_id (String)
      - payload       (String, JSON-encoded job_param)
      - ttl           (Number, Unix epoch seconds; TTL enabled)

    The container reads the run_id from the JOB_PARAM_REF env var and
    fetches the payload itself. The table name is set on the task
    definition via the JOB_PARAM_TABLE env var, not per-run.
    """

    def __init__(
        self,
        table_name: str,
        ddb_client: Optional[DynamoDBClient] = None,
    ) -> None:
        if not table_name:
            raise ValueError("ParamStore requires a table_name")
        self.table_name: str = table_name
        self.client: DynamoDBClient = ddb_client or boto3.client("dynamodb")

    def put(self, run_id: str, job_param: dict[str, Any]) -> None:
        """Write the payload. Raises ClientError on failure."""
        payload_json: str = json.dumps(job_param)

        # Log size so we can alert when approaching the 400KB item limit.
        logger.info(
            f"[ParamStore] [WRITE] run_id={run_id}, "
            f"payload_bytes={len(payload_json)}"
        )

        expires_at: int = int(time.time()) + PARAM_TTL_SECONDS

        self.client.put_item(
            TableName=self.table_name,
            Item={
                "run_id": {"S": run_id},
                "payload": {"S": payload_json},
                "ttl": {"N": str(expires_at)},
            },
        )
