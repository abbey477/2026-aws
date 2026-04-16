"""
Unit tests for TriggerEcsJob Lambda handler.

Tests:
1. Successful ECS task trigger — returns TRIGGERED with task_arn.
2. RunTask returns no tasks — returns TRIGGER_FAILED.
3. RunTask raises ClientError — returns TRIGGER_FAILED.
4. Runner config overrides infra defaults (task_definition, container_name).
5. Handler sets runner_name and runner_type on trigger_result.
6. Handler passes run_id as JOB_PARAM_REF env var (not job_param inline).
7. ParamStore writes job_param to DynamoDB with correct schema and TTL.
8. ParamStore write failure prevents RunTask from being called.
9. Handler returns TRIGGER_FAILED when param_store_table is missing.
"""

import json
import time

import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

from lambdas.trigger_ecs_job.handler import lambda_handler
from lambdas.trigger_ecs_job.ecs_trigger import trigger_ecs_task
from lambdas.trigger_ecs_job.param_store import ParamStore, PARAM_TTL_SECONDS


# ───────────────────────── Auto-mock write_log ─────────────────────────

@pytest.fixture(autouse=True)
def _mock_write_log():
    """Prevent write_log from hitting real DynamoDB in all tests."""
    with patch("lambdas.trigger_ecs_job.handler.write_log"):
        yield


# ───────────────────────── Helpers ─────────────────────────

def _make_event(runner_config_overrides=None):
    """Build a sample merged payload from GetConfig."""
    runner_config = {
        "cluster": "my-ecs-cluster",
        "subnets": ["subnet-aaa111", "subnet-bbb222"],
        "security_groups": ["sg-abc123"],
        "task_definition": "default-task-def",
        "container_name": "default-container",
        "instance_size": "small",
        "image": "",
        "param_store_table": "test-param-table",
    }
    if runner_config_overrides:
        runner_config.update(runner_config_overrides)

    return {
        "run_id": "run-001",
        "job_id": "client",
        "job_type": "sourcing",
        "status": "WAITING",
        "job_config": {
            "job_runner": {
                "type": "ECS_Fargate",
                "name": "S2S3",
                "config": runner_config,
            },
            "job_param": {
                "source": {"type": "API", "name": "RDI"},
                "batch_size": 1000,
                "output": ["s3_path"],
            },
            "next_jobs": [],
        },
    }


def _mock_ecs_client_success():
    """Return a mock ECS client that returns a successful RunTask response."""
    mock_client = MagicMock()
    mock_client.run_task.return_value = {
        "tasks": [
            {
                "taskArn": "arn:aws:ecs:us-east-1:123456789012:task/my-ecs-cluster/abc123def456",
                "lastStatus": "PROVISIONING",
            }
        ],
        "failures": [],
    }
    return mock_client


def _mock_ecs_client_no_tasks():
    """Return a mock ECS client where RunTask returns no tasks (failure)."""
    mock_client = MagicMock()
    mock_client.run_task.return_value = {
        "tasks": [],
        "failures": [
            {
                "arn": "arn:aws:ecs:us-east-1:123456789012:container-instance/xyz",
                "reason": "RESOURCE:MEMORY",
            }
        ],
    }
    return mock_client


def _mock_ecs_client_error():
    """Return a mock ECS client that raises a ClientError."""
    mock_client = MagicMock()
    mock_client.run_task.side_effect = ClientError(
        error_response={
            "Error": {
                "Code": "ClusterNotFoundException",
                "Message": "Cluster not found.",
            }
        },
        operation_name="RunTask",
    )
    return mock_client


def _make_param_store(ddb_client=None):
    """Build a ParamStore with a mock DynamoDB client by default."""
    return ParamStore(
        table_name="test-param-table",
        ddb_client=ddb_client or MagicMock(),
    )


# ───────────────────────── ParamStore Unit Tests ─────────────────────────

class TestParamStore:
    """Tests for the ParamStore class."""

    def test_put_writes_item_with_correct_schema(self):
        """ParamStore.put should write run_id, payload JSON, and a TTL."""
        mock_ddb = MagicMock()
        store = ParamStore(table_name="test-param-table", ddb_client=mock_ddb)
        job_param = {"batch_size": 1000, "source": "RDI"}

        store.put("run-001", job_param)

        mock_ddb.put_item.assert_called_once()
        call_kwargs = mock_ddb.put_item.call_args[1]
        assert call_kwargs["TableName"] == "test-param-table"

        item = call_kwargs["Item"]
        assert item["run_id"] == {"S": "run-001"}
        assert item["payload"] == {"S": json.dumps(job_param)}
        assert "ttl" in item
        assert item["ttl"]["N"].isdigit()

    def test_put_sets_ttl_roughly_seven_days_out(self):
        """TTL should be Unix epoch now + PARAM_TTL_SECONDS (with slack)."""
        mock_ddb = MagicMock()
        store = ParamStore(table_name="test-param-table", ddb_client=mock_ddb)

        before = int(time.time())
        store.put("run-001", {"foo": "bar"})
        after = int(time.time())

        ttl_value = int(mock_ddb.put_item.call_args[1]["Item"]["ttl"]["N"])
        assert before + PARAM_TTL_SECONDS <= ttl_value <= after + PARAM_TTL_SECONDS

    def test_init_rejects_empty_table_name(self):
        """ParamStore constructor should fail fast on missing table_name."""
        with pytest.raises(ValueError, match="table_name"):
            ParamStore(table_name="", ddb_client=MagicMock())

    def test_put_propagates_client_error(self):
        """ClientError from DynamoDB should bubble up to the caller."""
        mock_ddb = MagicMock()
        mock_ddb.put_item.side_effect = ClientError(
            error_response={
                "Error": {
                    "Code": "ResourceNotFoundException",
                    "Message": "Table not found.",
                }
            },
            operation_name="PutItem",
        )
        store = ParamStore(table_name="test-param-table", ddb_client=mock_ddb)

        with pytest.raises(ClientError):
            store.put("run-001", {"foo": "bar"})


# ───────────────────────── trigger_ecs_task Unit Tests ─────────────────────────

class TestTriggerEcsTask:
    """Tests for the trigger_ecs_task helper function."""

    def test_successful_trigger_returns_task_arn(self):
        """Happy path: RunTask returns a task with an ARN."""
        mock_ecs = _mock_ecs_client_success()
        event = _make_event()
        job_config = event["job_config"]
        job_param = job_config["job_param"]

        result = trigger_ecs_task(
            ecs_client=mock_ecs,
            job_config=job_config,
            job_param=job_param,
            run_id="run-001",
            param_store=_make_param_store(),
        )

        assert result["trigger_status"] == "TRIGGERED"
        assert "abc123def456" in result["task_arn"]
        assert "error" not in result

    def test_no_tasks_returned_trigger_failed(self):
        """RunTask returns empty tasks list — should mark TRIGGER_FAILED."""
        mock_ecs = _mock_ecs_client_no_tasks()
        event = _make_event()
        job_config = event["job_config"]
        job_param = job_config["job_param"]

        result = trigger_ecs_task(
            ecs_client=mock_ecs,
            job_config=job_config,
            job_param=job_param,
            run_id="run-001",
            param_store=_make_param_store(),
        )

        assert result["trigger_status"] == "TRIGGER_FAILED"
        assert result["task_arn"] == ""
        assert "error" in result

    def test_client_error_trigger_failed(self):
        """ClientError from ECS — should mark TRIGGER_FAILED."""
        mock_ecs = _mock_ecs_client_error()
        event = _make_event()
        job_config = event["job_config"]
        job_param = job_config["job_param"]

        result = trigger_ecs_task(
            ecs_client=mock_ecs,
            job_config=job_config,
            job_param=job_param,
            run_id="run-001",
            param_store=_make_param_store(),
        )

        assert result["trigger_status"] == "TRIGGER_FAILED"
        assert result["task_arn"] == ""
        assert "ClusterNotFoundException" in result["error"]

    def test_runner_config_overrides_defaults(self):
        """Runner config overrides should work correctly."""
        mock_ecs = _mock_ecs_client_success()
        event = _make_event(runner_config_overrides={
            "task_definition": "custom-task-def",
            "container_name": "custom-container",
        })
        job_config = event["job_config"]
        job_param = job_config["job_param"]

        trigger_ecs_task(
            ecs_client=mock_ecs,
            job_config=job_config,
            job_param=job_param,
            run_id="run-001",
            param_store=_make_param_store(),
        )

        call_kwargs = mock_ecs.run_task.call_args[1]
        assert call_kwargs["taskDefinition"] == "custom-task-def"
        overrides = call_kwargs["overrides"]["containerOverrides"][0]
        assert overrides["name"] == "custom-container"

    def test_run_id_passed_as_job_param_ref(self):
        """Container should receive JOB_PARAM_REF=run_id (not inline payload)."""
        mock_ecs = _mock_ecs_client_success()
        event = _make_event()
        job_config = event["job_config"]
        job_param = job_config["job_param"]

        trigger_ecs_task(
            ecs_client=mock_ecs,
            job_config=job_config,
            job_param=job_param,
            run_id="run-001",
            param_store=_make_param_store(),
        )

        call_kwargs = mock_ecs.run_task.call_args[1]
        env_vars = call_kwargs["overrides"]["containerOverrides"][0]["environment"]
        ref_var = next(e for e in env_vars if e["name"] == "JOB_PARAM_REF")
        assert ref_var["value"] == "run-001"

        # JOB_PARAM (the old inline var) should NOT be set.
        assert not any(e["name"] == "JOB_PARAM" for e in env_vars)

    def test_param_store_write_happens_before_run_task(self):
        """Order matters: payload must be written BEFORE RunTask is called."""
        mock_ecs = _mock_ecs_client_success()
        mock_store = MagicMock(spec=ParamStore)
        event = _make_event()
        job_config = event["job_config"]
        job_param = job_config["job_param"]

        # Use a shared call tracker to verify ordering.
        call_order = []
        mock_store.put.side_effect = lambda *a, **kw: call_order.append("put")
        mock_ecs.run_task.side_effect = lambda *a, **kw: (
            call_order.append("run_task"),
            {"tasks": [{"taskArn": "arn:aws:ecs:..."}], "failures": []},
        )[1]

        trigger_ecs_task(
            ecs_client=mock_ecs,
            job_config=job_config,
            job_param=job_param,
            run_id="run-001",
            param_store=mock_store,
        )

        assert call_order == ["put", "run_task"]

    def test_param_store_write_failure_prevents_run_task(self):
        """If DynamoDB write fails, RunTask must NOT be called."""
        mock_ecs = _mock_ecs_client_success()
        mock_store = MagicMock(spec=ParamStore)
        mock_store.put.side_effect = ClientError(
            error_response={
                "Error": {
                    "Code": "ResourceNotFoundException",
                    "Message": "Table not found.",
                }
            },
            operation_name="PutItem",
        )
        event = _make_event()
        job_config = event["job_config"]
        job_param = job_config["job_param"]

        result = trigger_ecs_task(
            ecs_client=mock_ecs,
            job_config=job_config,
            job_param=job_param,
            run_id="run-001",
            param_store=mock_store,
        )

        assert result["trigger_status"] == "TRIGGER_FAILED"
        assert result["task_arn"] == ""
        assert "param_store_write_failed" in result["error"]
        mock_ecs.run_task.assert_not_called()


# ───────────────────────── lambda_handler Integration Tests ─────────────────────────

class TestTriggerEcsJobHandler:
    """Tests for the full lambda_handler."""

    def test_handler_success_adds_trigger_result(self, monkeypatch):
        """Handler should add trigger_result with runner metadata on success."""
        mock_ecs = _mock_ecs_client_success()
        mock_ddb = MagicMock()
        monkeypatch.setattr(
            "lambdas.trigger_ecs_job.handler.boto3.client",
            lambda service: mock_ecs,
        )
        # ParamStore is instantiated inside the handler; patch boto3.client
        # there too. The single lambda above covers both ecs and dynamodb
        # since MagicMock accepts any method calls.
        monkeypatch.setattr(
            "lambdas.trigger_ecs_job.param_store.boto3.client",
            lambda service: mock_ddb,
        )

        event = _make_event()
        result = lambda_handler(event, None)

        assert "trigger_result" in result
        tr = result["trigger_result"]
        assert tr["trigger_status"] == "TRIGGERED"
        assert tr["runner_name"] == "S2S3"
        assert tr["runner_type"] == "ECS"
        assert "abc123def456" in tr["task_arn"]

    def test_handler_failure_adds_trigger_result(self, monkeypatch):
        """Handler should add trigger_result with TRIGGER_FAILED on error."""
        mock_ecs = _mock_ecs_client_no_tasks()
        mock_ddb = MagicMock()
        monkeypatch.setattr(
            "lambdas.trigger_ecs_job.handler.boto3.client",
            lambda service: mock_ecs,
        )
        monkeypatch.setattr(
            "lambdas.trigger_ecs_job.param_store.boto3.client",
            lambda service: mock_ddb,
        )

        event = _make_event()
        result = lambda_handler(event, None)

        tr = result["trigger_result"]
        assert tr["trigger_status"] == "TRIGGER_FAILED"
        assert tr["runner_name"] == "S2S3"
        assert tr["runner_type"] == "ECS"

    def test_handler_preserves_original_event_fields(self, monkeypatch):
        """Handler should return the original event fields plus trigger_result."""
        mock_ecs = _mock_ecs_client_success()
        mock_ddb = MagicMock()
        monkeypatch.setattr(
            "lambdas.trigger_ecs_job.handler.boto3.client",
            lambda service: mock_ecs,
        )
        monkeypatch.setattr(
            "lambdas.trigger_ecs_job.param_store.boto3.client",
            lambda service: mock_ddb,
        )

        event = _make_event()
        result = lambda_handler(event, None)

        assert result["run_id"] == "run-001"
        assert result["job_id"] == "client"
        assert result["job_config"]["job_runner"]["type"] == "ECS_Fargate"
        assert "trigger_result" in result

    def test_handler_missing_param_store_table_fails_fast(self, monkeypatch):
        """Missing param_store_table in config — TRIGGER_FAILED, no ECS call."""
        mock_ecs = _mock_ecs_client_success()
        monkeypatch.setattr(
            "lambdas.trigger_ecs_job.handler.boto3.client",
            lambda service: mock_ecs,
        )

        event = _make_event(runner_config_overrides={"param_store_table": ""})
        result = lambda_handler(event, None)

        tr = result["trigger_result"]
        assert tr["trigger_status"] == "TRIGGER_FAILED"
        assert "param_store_config_error" in tr["error"]
        mock_ecs.run_task.assert_not_called()
