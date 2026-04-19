"""
Unit tests for GetConfig Lambda handler — v2.

Uses moto to mock DynamoDB and tests:
1. Successful config retrieval (job_run + job_config, including v2 pre_steps).
2. Missing / empty / None run_id in input.
3. run_id not found in job_run table.
4. job_config not found for given job_id + job_type.
5. job_run record missing job_id or job_type fields.
6. DynamoDB ClientError propagation.
7. Side effects: write_log called on success, NOT called on failure.
8. v2: pre_steps pass through as-is (including empty array and missing field).
"""

import pytest
import boto3
from moto import mock_aws
from unittest.mock import patch
from botocore.exceptions import ClientError

from lambdas.get_config.handler import lambda_handler
from lambdas.get_config.dynamodb_ops import get_job_run, get_job_config


# ---------------------------------------------------------------------------
# Helpers — seed data builders
# ---------------------------------------------------------------------------

def _make_job_run_item(**overrides) -> dict:
    """Build a job_run item with sensible defaults; override any field."""
    base = {
        "run_id": "run-001",
        "job_id": "client",
        "job_type": "sourcing",
        "trigger_type": "SCHEDULER",
        "status": "WAITING",
        "start_time": "",
        "end_time": "",
        "next_scheduled_run_time": "",
        "last_heartbeat_time": "",
        "expiry_time": "",
        "mark_for_delete": False,
        "custom_attributes": {},
        "error": "",
        "delete_at": 0,
    }
    base.update(overrides)
    return base


def _make_job_config_item(**overrides) -> dict:
    """
    Build a job_config item matching the v2 authoritative shape.

    job_param internals are intentionally minimal — they're treated as an
    opaque pass-through blob for now. pre_steps (v2) is included with
    both a simple step and a step that carries extra fields (polymorphic shape).
    """
    base = {
        "job_id": "client",
        "job_type": "sourcing",
        "enabled": True,
        "trigger_type": "SCHEDULER",
        "run_frequency_in_mins": 60,
        "concurrent_runs_enabled": False,
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
                "image": "",
            },
        },
        # v2: pre_steps — polymorphic array, items discriminated by `type`
        "pre_steps": [
            {"type": "change_since_append"},
            {
                "type": "ddb_config_pull",
                "tables": ["service_config", "table_config"],
            },
        ],
        "job_param": {
            # Opaque blob — tests do not assert on internal structure
            "source": {"type": "API", "name": "RDI"},
            "batch_size": 1000,
            "thread_count": 10,
        },
        "next_jobs": [
            {"type": "silver_load", "id": "dbr_client"},
        ],
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    base.update(overrides)
    return base


def _raise_access_denied(*args, **kwargs):
    """Helper: stub function that raises a DynamoDB AccessDeniedException."""
    raise ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "Denied"}},
        "GetItem",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_write_log():
    """Prevent write_log from hitting real DynamoDB in all tests."""
    with patch("lambdas.get_config.handler.write_log") as mock:
        yield mock


@pytest.fixture
def dynamodb_tables():
    """Create mock DynamoDB tables, seeded with v2 default data."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        # Create job_run table (partition key: run_id)
        job_run_table = dynamodb.create_table(
            TableName="job_run",
            KeySchema=[{"AttributeName": "run_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "run_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Create job_config table (partition key: job_id, sort key: job_type)
        job_config_table = dynamodb.create_table(
            TableName="job_config",
            KeySchema=[
                {"AttributeName": "job_id", "KeyType": "HASH"},
                {"AttributeName": "job_type", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "job_id", "AttributeType": "S"},
                {"AttributeName": "job_type", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Seed default happy-path data (v2 shape)
        job_run_table.put_item(Item=_make_job_run_item())
        job_config_table.put_item(Item=_make_job_config_item())

        yield dynamodb


@pytest.fixture
def patched_handler(dynamodb_tables, monkeypatch):
    """Patch get_dynamodb_resource so the handler uses the mock tables."""
    monkeypatch.setattr(
        "lambdas.get_config.dynamodb_ops.get_dynamodb_resource",
        lambda: dynamodb_tables,
    )
    return dynamodb_tables


# ---------------------------------------------------------------------------
# Handler tests
# ---------------------------------------------------------------------------

class TestGetConfigLambda:
    """Tests for the GetConfig Lambda handler."""

    def test_successful_config_retrieval(self, patched_handler, _mock_write_log):
        """Happy path: valid run_id returns merged job_run + job_config (v2 shape)."""
        event = {"run_id": "run-001"}
        result = lambda_handler(event, None)

        # --- job_run fields spread at top level ---
        assert result["run_id"] == "run-001"
        assert result["job_id"] == "client"
        assert result["job_type"] == "sourcing"
        assert result["status"] == "WAITING"
        assert result["trigger_type"] == "SCHEDULER"
        assert result["custom_attributes"] == {}

        # --- job_config nested under 'job_config' key ---
        assert "job_config" in result
        job_config = result["job_config"]
        assert job_config["enabled"] is True
        assert job_config["job_runner"]["name"] == "S2S3"
        assert job_config["job_runner"]["type"] == "ECS_Fargate"

        # Verify job_runner.config infra fields survived the round trip
        runner_cfg = job_config["job_runner"]["config"]
        assert runner_cfg["cluster"] == "my-ecs-cluster"
        assert runner_cfg["subnets"] == ["subnet-aaa111", "subnet-bbb222"]
        assert runner_cfg["security_groups"] == ["sg-abc123"]
        assert runner_cfg["task_definition"] == "default-task-def"
        assert runner_cfg["container_name"] == "default-container"
        assert runner_cfg["instance_size"] == "small"
        assert runner_cfg["image"] == ""

        # --- next_jobs flows through ---
        assert len(job_config["next_jobs"]) == 1
        assert job_config["next_jobs"][0]["id"] == "dbr_client"

        # --- write_log called on success ---
        _mock_write_log.assert_called_once_with(
            run_id="run-001",
            job_id="client",
            stage="GetConfig",
            status="SUCCESS",
        )

    def test_pre_steps_passes_through(self, patched_handler):
        """v2: pre_steps array flows through the handler unchanged."""
        result = lambda_handler({"run_id": "run-001"}, None)

        assert "pre_steps" in result["job_config"]
        pre_steps = result["job_config"]["pre_steps"]
        assert isinstance(pre_steps, list)
        assert len(pre_steps) == 2

        # Simple step — only has type
        assert pre_steps[0] == {"type": "change_since_append"}

        # Polymorphic step — type + extra fields specific to the type
        assert pre_steps[1]["type"] == "ddb_config_pull"
        assert pre_steps[1]["tables"] == ["service_config", "table_config"]

    def test_pre_steps_empty_array_passes_through(self, patched_handler):
        """v2: a job_config with empty pre_steps returns empty pre_steps."""
        table = patched_handler.Table("job_config")
        table.put_item(Item=_make_job_config_item(
            job_id="client",
            job_type="sourcing",
            pre_steps=[],
        ))

        result = lambda_handler({"run_id": "run-001"}, None)

        assert result["job_config"]["pre_steps"] == []

    def test_pre_steps_missing_field_handled_gracefully(self, patched_handler):
        """
        v2: a job_config row without pre_steps at all (legacy/v1 row)
        still succeeds — the key just won't appear in output.
        """
        # Seed a job_config row without pre_steps
        item = _make_job_config_item(
            job_id="legacy-client",
            job_type="legacy-type",
        )
        del item["pre_steps"]
        patched_handler.Table("job_config").put_item(Item=item)

        # And a matching job_run pointing to it
        patched_handler.Table("job_run").put_item(Item=_make_job_run_item(
            run_id="run-legacy",
            job_id="legacy-client",
            job_type="legacy-type",
        ))

        result = lambda_handler({"run_id": "run-legacy"}, None)

        # Handler should not crash and pre_steps simply won't be present
        assert "pre_steps" not in result["job_config"]

    @pytest.mark.parametrize("bad_event", [
        {},
        {"run_id": ""},
        {"run_id": None},
    ])
    def test_invalid_run_id_raises_error(
        self, patched_handler, _mock_write_log, bad_event,
    ):
        """Missing, empty, or None run_id all raise ValueError."""
        with pytest.raises(ValueError, match="Missing required input"):
            lambda_handler(bad_event, None)

        _mock_write_log.assert_not_called()

    def test_run_id_not_found_raises_error(self, patched_handler, _mock_write_log):
        """Non-existent run_id raises ValueError."""
        with pytest.raises(ValueError, match="No job_run found"):
            lambda_handler({"run_id": "nonexistent-id"}, None)

        _mock_write_log.assert_not_called()

    def test_job_config_not_found_raises_error(self, patched_handler, _mock_write_log):
        """Missing job_config for given job_id/job_type raises ValueError."""
        table = patched_handler.Table("job_run")
        table.put_item(Item=_make_job_run_item(
            run_id="run-orphan",
            job_type="nonexistent_type",
        ))

        with pytest.raises(ValueError, match="No job_config found"):
            lambda_handler({"run_id": "run-orphan"}, None)

        _mock_write_log.assert_not_called()

    def test_job_run_missing_job_id_raises_error(self, patched_handler, _mock_write_log):
        """job_run record without job_id field raises ValueError."""
        table = patched_handler.Table("job_run")
        table.put_item(Item={
            "run_id": "run-bad",
            "job_type": "sourcing",
            "status": "WAITING",
        })

        with pytest.raises(ValueError, match="missing 'job_id' or 'job_type'"):
            lambda_handler({"run_id": "run-bad"}, None)

        _mock_write_log.assert_not_called()

    def test_job_run_missing_job_type_raises_error(self, patched_handler, _mock_write_log):
        """job_run record without job_type field raises ValueError."""
        table = patched_handler.Table("job_run")
        table.put_item(Item={
            "run_id": "run-bad-2",
            "job_id": "client",
            "status": "WAITING",
        })

        with pytest.raises(ValueError, match="missing 'job_id' or 'job_type'"):
            lambda_handler({"run_id": "run-bad-2"}, None)

        _mock_write_log.assert_not_called()

    def test_dynamodb_client_error_propagates(self, patched_handler, monkeypatch, _mock_write_log):
        """ClientError from DynamoDB surfaces to caller instead of being swallowed."""
        monkeypatch.setattr(
            "lambdas.get_config.handler.get_job_run",
            _raise_access_denied,
        )

        with pytest.raises(ClientError):
            lambda_handler({"run_id": "run-001"}, None)

        _mock_write_log.assert_not_called()


# ---------------------------------------------------------------------------
# Repository function tests — tested in isolation
# ---------------------------------------------------------------------------

class TestGetJobRun:
    """Tests for the get_job_run repository function."""

    def test_returns_item_when_found(self, dynamodb_tables):
        table = dynamodb_tables.Table("job_run")
        result = get_job_run(table, "run-001")
        assert result["run_id"] == "run-001"
        assert result["job_id"] == "client"

    def test_raises_when_not_found(self, dynamodb_tables):
        table = dynamodb_tables.Table("job_run")
        with pytest.raises(ValueError, match="No job_run found"):
            get_job_run(table, "does-not-exist")

    def test_raises_on_client_error(self, dynamodb_tables, monkeypatch):
        """ClientError from DynamoDB is re-raised, not swallowed."""
        table = dynamodb_tables.Table("job_run")
        monkeypatch.setattr(table, "get_item", _raise_access_denied)

        with pytest.raises(ClientError):
            get_job_run(table, "run-001")


class TestGetJobConfig:
    """Tests for the get_job_config repository function."""

    def test_returns_item_when_found(self, dynamodb_tables):
        table = dynamodb_tables.Table("job_config")
        result = get_job_config(table, "client", "sourcing")
        assert result["job_id"] == "client"
        assert result["job_runner"]["name"] == "S2S3"

    def test_returns_pre_steps_when_present(self, dynamodb_tables):
        """v2: repository returns pre_steps field when it exists on the row."""
        table = dynamodb_tables.Table("job_config")
        result = get_job_config(table, "client", "sourcing")
        assert "pre_steps" in result
        assert len(result["pre_steps"]) == 2
        assert result["pre_steps"][0]["type"] == "change_since_append"
        assert result["pre_steps"][1]["type"] == "ddb_config_pull"

    def test_raises_when_not_found(self, dynamodb_tables):
        table = dynamodb_tables.Table("job_config")
        with pytest.raises(ValueError, match="No job_config found"):
            get_job_config(table, "client", "nonexistent")

    def test_raises_on_client_error(self, dynamodb_tables, monkeypatch):
        """ClientError from DynamoDB is re-raised, not swallowed."""
        table = dynamodb_tables.Table("job_config")
        monkeypatch.setattr(table, "get_item", _raise_access_denied)

        with pytest.raises(ClientError):
            get_job_config(table, "client", "sourcing")
