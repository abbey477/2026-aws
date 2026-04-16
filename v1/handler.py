"""
TriggerEcsJob Lambda Handler

Triggers an ECS Fargate task using the RunTask API.
Called by the state machine when job_config.job_runner.type is ECS_Fargate.

Input:  Full merged payload from GetConfig (job_run + job_config).
Output: Same payload + trigger_result with task_arn and trigger_status.

job_param is written to DynamoDB and fetched by the container on startup,
rather than passed inline (Fargate overrides are capped at 8KB total).
See PARAM_STORE_CONTRACT.md for the container-side contract.
"""

import logging
from datetime import datetime, timezone
from typing import Any

import boto3
from mypy_boto3_ecs.client import ECSClient

from lambdas.log_to_dynamo import write_log

from .ecs_trigger import trigger_ecs_task
from .param_store import ParamStore

logger: logging.Logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _log(step: str, details: dict[str, Any]) -> None:
    """Structured info log — every line has a step tag + key-value pairs."""
    detail_str: str = ", ".join(f"{k}={v}" for k, v in details.items())
    logger.info(f"[TriggerEcsJob] [{step}] {detail_str}")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda entry point. Input: merged payload from GetConfig.
    Output: same payload + trigger_result.
    """
    timestamp: str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id: str = event.get("run_id", "UNKNOWN")
    job_config: dict[str, Any] = event.get("job_config", {})
    job_param: dict[str, Any] = job_config.get("job_param", {})
    job_runner: dict[str, Any] = job_config.get("job_runner", {})
    runner_config: dict[str, Any] = job_runner.get("config", {})
    runner_name: str = job_runner.get("name", "")

    _log("HANDLER_START", {
        "timestamp": timestamp,
        "run_id": run_id,
        "runner_name": runner_name,
    })

    # Build the store before calling ECS — if config is bad, fail fast.
    trigger_result: dict[str, Any]
    try:
        param_store: ParamStore = ParamStore(
            table_name=runner_config.get("param_store_table", ""),
        )
    except ValueError as e:
        _log("PARAM_STORE_CONFIG_ERROR", {"error": str(e)})
        trigger_result = {
            "trigger_status": "TRIGGER_FAILED",
            "task_arn": "",
            "error": f"param_store_config_error: {e}",
        }
    else:
        ecs_client: ECSClient = boto3.client("ecs")
        trigger_result = trigger_ecs_task(
            ecs_client=ecs_client,
            job_config=job_config,
            job_param=job_param,
            run_id=run_id,
            param_store=param_store,
        )

    trigger_result["runner_name"] = runner_name
    trigger_result["runner_type"] = "ECS"
    event["trigger_result"] = trigger_result

    write_log(
        run_id=run_id,
        job_id=event.get("job_id", ""),
        stage="TriggerEcsJob",
        status=trigger_result.get("trigger_status", "UNKNOWN"),
    )

    _log("HANDLER_COMPLETE", {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": run_id,
        "trigger_status": trigger_result.get("trigger_status"),
        "task_arn": trigger_result.get("task_arn", ""),
    })

    return event
