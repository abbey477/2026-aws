# Simulating AWS Services for Lambda Testing

Full simulation stack for testing your Lambda locally when services are not ready.

---

## Overview

| Service | Simulation Tool | Reason |
|---|---|---|
| DynamoDB | `moto` | Called via AWS SDK (boto3) |
| ECS Fargate | `moto` | Called via AWS SDK (boto3) |
| Databricks | `responses` | Called via HTTP REST API |

All three work together in the same test suite:

```
pytest
  │
  ├── moto ──► fakes DynamoDB
  ├── moto ──► fakes ECS Fargate
  └── responses ──► fakes Databricks REST API
```

---

## Installation

```bash
pip install moto boto3 pytest responses
```

---

## Project Structure

```
my_project/
├── my_lambda.py
└── tests/
    └── test_lambda.py
```

---

## Lambda Structure

Make all endpoints and config configurable via environment variables
so you can easily swap between local simulation and real AWS:

```python
# my_lambda.py
import os
import json
import boto3
import requests

DYNAMODB_ENDPOINT = os.getenv('DYNAMODB_ENDPOINT', None)
DATABRICKS_HOST   = os.getenv('DATABRICKS_HOST', 'https://my-workspace.azuredatabricks.net')
DATABRICKS_TOKEN  = os.getenv('DATABRICKS_TOKEN', 'fake-token')
DATABRICKS_JOB_ID = os.getenv('DATABRICKS_JOB_ID', '123')
ECS_CLUSTER       = os.getenv('ECS_CLUSTER', 'my-cluster')
ECS_TASK_DEF      = os.getenv('ECS_TASK_DEF', 'my-task-definition')

def get_dynamodb():
    kwargs = {'region_name': 'us-east-1'}
    if DYNAMODB_ENDPOINT:
        kwargs['endpoint_url'] = DYNAMODB_ENDPOINT
        kwargs['aws_access_key_id'] = 'fake'
        kwargs['aws_secret_access_key'] = 'fake'
    return boto3.resource('dynamodb', **kwargs)

def get_ecs_client():
    return boto3.client('ecs', region_name='us-east-1')

def trigger_ecs_task():
    ecs = get_ecs_client()
    response = ecs.run_task(
        cluster=ECS_CLUSTER,
        taskDefinition=ECS_TASK_DEF,
        launchType='FARGATE',
        networkConfiguration={
            'awsvpcConfiguration': {
                'subnets': ['subnet-12345'],
                'assignPublicIp': 'ENABLED'
            }
        }
    )
    # Fire and forget — just return task ARN
    task_arn = response['tasks'][0]['taskArn']
    return task_arn

def trigger_databricks_job(params):
    response = requests.post(
        f'{DATABRICKS_HOST}/api/2.1/jobs/run-now',
        headers={'Authorization': f'Bearer {DATABRICKS_TOKEN}'},
        json={
            'job_id': DATABRICKS_JOB_ID,
            'notebook_params': params
        }
    )
    return response.json()  # returns {'run_id': 456}

def handler(event, context):
    dynamodb = get_dynamodb()
    table = dynamodb.Table('ConfigTable')

    # Read config from DynamoDB
    response = table.get_item(Key={'id': event['id']})
    config = response.get('Item', {})

    job_runner = config.get('job_runner')

    if job_runner == 'S32S':
        # Trigger ECS Fargate (fire and forget)
        task_arn = trigger_ecs_task()
        return {
            'statusCode': 200,
            'body': json.dumps({'task_arn': task_arn})
        }

    elif job_runner == 'S2S3':
        # Trigger Databricks job (fire and forget)
        dbr_response = trigger_databricks_job({'entity_id': event['id']})
        return {
            'statusCode': 200,
            'body': json.dumps({'run_id': dbr_response.get('run_id')})
        }

    return {'statusCode': 400, 'body': json.dumps({'error': 'unknown job runner'})}
```

---

## Option 1 — Moto: Simulating DynamoDB and ECS Fargate

Moto intercepts all boto3 calls in-process — no extra server needed.

### DynamoDB simulation

```python
# tests/test_lambda.py
import os
import boto3
import pytest
from moto import mock_aws

os.environ['ECS_CLUSTER']   = 'my-cluster'
os.environ['ECS_TASK_DEF']  = 'my-task-definition'
os.environ['DATABRICKS_HOST'] = 'https://fake-databricks'
os.environ['DATABRICKS_TOKEN'] = 'fake-token'
os.environ['DATABRICKS_JOB_ID'] = '999'

@pytest.fixture
def aws_setup():
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Create fake DynamoDB table
        table = dynamodb.create_table(
            TableName='ConfigTable',
            KeySchema=[{'AttributeName': 'id', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'id', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST'
        )

        # Seed fake config data
        table.put_item(Item={
            'id': '123',
            'job_runner': 'S32S',
            'status': 'PENDING'
        })

        # Create fake ECS cluster
        ecs = boto3.client('ecs', region_name='us-east-1')
        ecs.create_cluster(clusterName='my-cluster')

        # Register fake task definition
        ecs.register_task_definition(
            family='my-task-definition',
            networkMode='awsvpc',
            containerDefinitions=[
                {
                    'name': 'my-container',
                    'image': 'my-image:latest',
                    'memory': 512,
                    'cpu': 256
                }
            ],
            requiresCompatibilities=['FARGATE'],
            cpu='256',
            memory='512'
        )

        yield dynamodb, ecs
```

### ECS Fargate simulation (fire and forget)

```python
@mock_aws
def test_lambda_triggers_ecs(aws_setup):
    dynamodb, ecs = aws_setup

    from my_lambda import handler
    result = handler({'id': '123'}, {})

    # Assert Lambda returned successfully
    assert result['statusCode'] == 200

    # Assert ECS task was triggered
    import json
    body = json.loads(result['body'])
    assert 'task_arn' in body

    # Verify task was actually run in fake ECS
    tasks = ecs.list_tasks(cluster='my-cluster')
    assert len(tasks['taskArns']) > 0
```

---

## Option 2 — responses: Simulating Databricks REST API

The `responses` library intercepts HTTP calls made by the `requests` library.

### Trigger simulation

```python
import responses as responses_mock
import json

@mock_aws
@responses_mock.activate
def test_lambda_triggers_databricks():
    # Setup DynamoDB with S2S3 config
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    table = dynamodb.Table('ConfigTable')
    table.put_item(Item={
        'id': '456',
        'job_runner': 'S2S3',
        'status': 'PENDING'
    })

    # Fake Databricks job trigger response
    responses_mock.add(
        responses_mock.POST,
        'https://fake-databricks/api/2.1/jobs/run-now',
        json={'run_id': 789},
        status=200
    )

    from my_lambda import handler
    result = handler({'id': '456'}, {})

    assert result['statusCode'] == 200
    body = json.loads(result['body'])
    assert body['run_id'] == 789
```

### Simulating different Databricks outcomes

One of the biggest benefits of mocking — test scenarios the real service
can't easily reproduce yet:

```python
# Test Databricks API error
@mock_aws
@responses_mock.activate
def test_lambda_handles_databricks_error():
    responses_mock.add(
        responses_mock.POST,
        'https://fake-databricks/api/2.1/jobs/run-now',
        json={'error': 'Service unavailable'},
        status=503
    )

    from my_lambda import handler
    result = handler({'id': '456'}, {})
    assert result['statusCode'] == 500


# Test Databricks poll — job still running
@responses_mock.activate
def test_wait_monitor_job_still_running():
    responses_mock.add(
        responses_mock.GET,
        'https://fake-databricks/api/2.1/jobs/runs/get',
        json={'state': {'life_cycle_state': 'RUNNING'}},
        status=200
    )
    # Assert your wait/monitor handles this correctly


# Test Databricks poll — job complete
@responses_mock.activate
def test_wait_monitor_job_complete():
    responses_mock.add(
        responses_mock.GET,
        'https://fake-databricks/api/2.1/jobs/runs/get',
        json={
            'state': {
                'life_cycle_state': 'TERMINATED',
                'result_state': 'SUCCESS'
            }
        },
        status=200
    )
    # Assert your wait/monitor writes COMPLETE to DynamoDB


# Test Databricks poll — job failed
@responses_mock.activate
def test_wait_monitor_job_failed():
    responses_mock.add(
        responses_mock.GET,
        'https://fake-databricks/api/2.1/jobs/runs/get',
        json={
            'state': {
                'life_cycle_state': 'TERMINATED',
                'result_state': 'FAILED',
                'state_message': 'Out of memory'
            }
        },
        status=200
    )
    # Assert your wait/monitor writes FAILED to DynamoDB
```

---

## Full Test Suite Together

```python
# tests/test_lambda.py
import os
import json
import boto3
import pytest
import responses as responses_mock
from moto import mock_aws

# Set env vars before importing Lambda
os.environ['ECS_CLUSTER']      = 'my-cluster'
os.environ['ECS_TASK_DEF']     = 'my-task-definition'
os.environ['DATABRICKS_HOST']  = 'https://fake-databricks'
os.environ['DATABRICKS_TOKEN'] = 'fake-token'
os.environ['DATABRICKS_JOB_ID'] = '999'

@pytest.fixture
def aws_resources():
    with mock_aws():
        # DynamoDB
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        table = dynamodb.create_table(
            TableName='ConfigTable',
            KeySchema=[{'AttributeName': 'id', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'id', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST'
        )

        # ECS
        ecs = boto3.client('ecs', region_name='us-east-1')
        ecs.create_cluster(clusterName='my-cluster')
        ecs.register_task_definition(
            family='my-task-definition',
            networkMode='awsvpc',
            containerDefinitions=[{
                'name': 'my-container',
                'image': 'my-image:latest',
                'memory': 512,
                'cpu': 256
            }],
            requiresCompatibilities=['FARGATE'],
            cpu='256',
            memory='512'
        )

        yield table, ecs


@mock_aws
def test_s32s_triggers_ecs(aws_resources):
    table, ecs = aws_resources
    table.put_item(Item={'id': '123', 'job_runner': 'S32S', 'status': 'PENDING'})

    from my_lambda import handler
    result = handler({'id': '123'}, {})

    assert result['statusCode'] == 200
    assert 'task_arn' in json.loads(result['body'])


@mock_aws
@responses_mock.activate
def test_s2s3_triggers_databricks(aws_resources):
    table, _ = aws_resources
    table.put_item(Item={'id': '456', 'job_runner': 'S2S3', 'status': 'PENDING'})

    responses_mock.add(
        responses_mock.POST,
        'https://fake-databricks/api/2.1/jobs/run-now',
        json={'run_id': 789},
        status=200
    )

    from my_lambda import handler
    result = handler({'id': '456'}, {})

    assert result['statusCode'] == 200
    assert json.loads(result['body'])['run_id'] == 789
```

---

## Running the Tests

```bash
pytest tests/ -v
```

---

## Databricks Job Status Reference

When simulating the Wait & Monitor polling, these are the states to cover:

| life_cycle_state | result_state | Meaning |
|---|---|---|
| `PENDING` | — | Job queued |
| `RUNNING` | — | Job in progress |
| `TERMINATED` | `SUCCESS` | Job completed successfully |
| `TERMINATED` | `FAILED` | Job failed |
| `TERMINATED` | `TIMEDOUT` | Job exceeded max duration |
| `TERMINATED` | `CANCELED` | Job was manually canceled |
| `INTERNAL_ERROR` | — | Databricks platform error |
