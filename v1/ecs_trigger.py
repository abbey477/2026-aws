"""
ECS Fargate task trigger.

Writes job_param to the param store first, then launches the task with
the run_id in the JOB_PARAM_REF env var. The container fetches the
payload from DynamoDB on startup.
"""

import logging
from typing import Any

from botocore.exceptions import ClientError
from mypy_boto3_ecs.client import ECSClient

from .param_store import ParamStore

logger: logging.Logger = logging.getLogger(__name__)


def _log(step: str, details: dict[str, Any]) -> None:
    """Structured info log — every line has a step tag + key-value pairs."""
    detail_str: str = ", ".join(f"{k}={v}" for k, v in details.items())
    logger.info(f"[TriggerEcsJob] [{step}] {detail_str}")


def trigger_ecs_task(
    ecs_client: ECSClient,
    job_config: dict[str, Any],
    job_param: dict[str, Any],
    run_id: str,
    param_store: ParamStore,
) -> dict[str, Any]:
    """
    Trigger an ECS Fargate task. Returns a dict with trigger_status,
    task_arn, and optionally error.
    """
    runner_config: dict[str, Any] = (
        job_config.get("job_runner", {}).get("config", {})
    )

    ecs_cluster: str = runner_config.get("cluster", "")
    ecs_subnets: list[str] = runner_config.get("subnets", [])
    ecs_security_groups: list[str] = runner_config.get("security_groups", [])
    task_definition: str = runner_config.get("task_definition", "")
    container_name: str = runner_config.get("container_name", "")
    image: str = runner_config.get("image", "")

    _log("ECS_TRIGGER_START", {
        "cluster": ecs_cluster,
        "task_definition": task_definition,
        "container_name": container_name,
        "image": image or "N/A",
        "job_param_keys": list(job_param.keys()),
        "run_id": run_id,
    })

    # Write payload first. If this fails, no task is launched — avoids
    # orphan containers looking for a payload that isn't there.
    try:
        param_store.put(run_id, job_param)
    except ClientError as e:
        _log("PARAM_STORE_WRITE_FAILED", {
            "run_id": run_id,
            "error_code": e.response["Error"]["Code"],
            "error_message": e.response["Error"]["Message"],
        })
        return {
            "trigger_status": "TRIGGER_FAILED",
            "task_arn": "",
            "error": f"param_store_write_failed: {e}",
        }

    try:
        response: dict[str, Any] = ecs_client.run_task(
            cluster=ecs_cluster,
            taskDefinition=task_definition,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": ecs_subnets,
                    "securityGroups": ecs_security_groups,
                    "assignPublicIp": "DISABLED",
                }
            },
            overrides={
                "containerOverrides": [
                    {
                        "name": container_name,
                        "environment": [
                            {"name": "JOB_PARAM_REF", "value": run_id},
                        ],
                    }
                ]
            },
        )

        # RunTask can return 200 with empty `tasks` if placement fails
        # (no capacity, bad subnets, etc.) — always check.
        tasks: list[dict[str, Any]] = response.get("tasks", [])
        if not tasks:
            failures: list[dict[str, Any]] = response.get("failures", [])
            _log("ECS_TRIGGER_FAILED", {
                "reason": "RunTask returned no tasks",
                "failures": str(failures),
            })
            return {
                "trigger_status": "TRIGGER_FAILED",
                "task_arn": "",
                "error": str(failures),
            }

        task_arn: str = tasks[0]["taskArn"]
        _log("ECS_TRIGGER_SUCCESS", {"task_arn": task_arn})
        return {
            "trigger_status": "TRIGGERED",
            "task_arn": task_arn,
        }

    except ClientError as e:
        _log("ECS_CLIENT_ERROR", {
            "error_code": e.response["Error"]["Code"],
            "error_message": e.response["Error"]["Message"],
        })
        return {
            "trigger_status": "TRIGGER_FAILED",
            "task_arn": "",
            "error": str(e),
        }
