# Simulating DynamoDB for Lambda Testing

Two options to simulate DynamoDB locally when the real table is not ready yet.

---

## Option 1 — Moto (Python)

### Setup

```bash
pip install moto boto3 pytest
```

That's it — no other installs needed.

### Project Structure

```
my_project/
├── my_lambda.py
└── tests/
    └── test_lambda.py
```

### Usage

```python
import boto3
import pytest
from moto import mock_aws

@mock_aws
def test_lambda_reads_config():
    # 1. Create fake table
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    dynamodb.create_table(
        TableName='ConfigTable',
        KeySchema=[{'AttributeName': 'id', 'KeyType': 'HASH'}],
        AttributeDefinitions=[{'AttributeName': 'id', 'AttributeType': 'S'}],
        BillingMode='PAY_PER_REQUEST'
    )

    # 2. Seed fake data
    table = dynamodb.Table('ConfigTable')
    table.put_item(Item={'id': '123', 'job_runner': 'S32S', 'status': 'PENDING'})

    # 3. Call your Lambda handler directly
    from my_lambda import handler
    result = handler({'id': '123'}, {})
    assert result['statusCode'] == 200
```

### Pros
- Pure Python, no extra tools
- Runs inside your test process
- Fast — spins up and tears down per test
- Works with pytest natively

### Cons
- Occasional gaps vs real DynamoDB behaviour
- Resets after every test (no persistence)

---

## Option 2 — DynamoDB Local JAR (Java)

### Setup

**Step 1 — Check Java is installed:**
```bash
java -version
```

**Step 2 — Download DynamoDB Local from AWS:**
- Go to: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBLocal.DownloadingAndRunning.html
- Download the zip and extract it — you'll get:

```
dynamodb_local/
├── DynamoDBLocal.jar
└── DynamoDBLocal_lib/
```

**Step 3 — Start it:**
```bash
java -Djava.library.path=./DynamoDBLocal_lib -jar DynamoDBLocal.jar -inMemory
```

### Usage

```python
import boto3
import pytest
import os

@pytest.fixture
def dynamodb():
    # Point boto3 to the local JAR instead of real AWS
    return boto3.resource(
        'dynamodb',
        region_name='us-east-1',
        endpoint_url='http://localhost:8000',
        aws_access_key_id='fake',
        aws_secret_access_key='fake'
    )

def test_lambda_reads_config(dynamodb):
    # 1. Create fake table
    dynamodb.create_table(
        TableName='ConfigTable',
        KeySchema=[{'AttributeName': 'id', 'KeyType': 'HASH'}],
        AttributeDefinitions=[{'AttributeName': 'id', 'AttributeType': 'S'}],
        BillingMode='PAY_PER_REQUEST'
    )

    # 2. Seed fake data
    table = dynamodb.Table('ConfigTable')
    table.put_item(Item={'id': '123', 'job_runner': 'S32S', 'status': 'PENDING'})

    # 3. Set env var so Lambda points to local JAR
    os.environ['DYNAMODB_ENDPOINT'] = 'http://localhost:8000'

    # 4. Call your Lambda handler
    from my_lambda import handler
    result = handler({'id': '123'}, {})
    assert result['statusCode'] == 200
```

### Pros
- Very high fidelity — closest to real DynamoDB
- Can persist data between runs (remove `-inMemory` flag)
- Useful for manual testing too, not just automated tests

### Cons
- Requires Java installed
- Must start the JAR separately before running tests
- Slightly more setup effort

---

## Side by Side Comparison

| | Moto | DynamoDB Local JAR |
|---|---|---|
| Language | Python only | Any language |
| Requires Java | No | Yes |
| Extra process | No | Yes (JAR must be running) |
| Fidelity | Very good | Closest to real AWS |
| Persistent data | No | Optional |
| Speed | Faster | Slightly slower |
| Setup effort | `pip install moto` | Download + run JAR |
| Best for | Unit tests | Integration tests |

---

## Recommendation

Start with **Moto** — you can be writing tests in 5 minutes.
Add the JAR later if you hit edge cases where Moto behaves differently from real DynamoDB.

---

## Lambda Structure (for both options)

Make sure your Lambda reads the DynamoDB endpoint from an environment variable
so you can easily swap between local and real AWS:

```python
# my_lambda.py
import os
import json
import boto3

DYNAMODB_ENDPOINT = os.getenv('DYNAMODB_ENDPOINT', None)

def get_dynamodb():
    kwargs = {'region_name': 'us-east-1'}
    if DYNAMODB_ENDPOINT:
        kwargs['endpoint_url'] = DYNAMODB_ENDPOINT
        kwargs['aws_access_key_id'] = 'fake'
        kwargs['aws_secret_access_key'] = 'fake'
    return boto3.resource('dynamodb', **kwargs)

def handler(event, context):
    dynamodb = get_dynamodb()
    table = dynamodb.Table('ConfigTable')

    # Read config
    response = table.get_item(Key={'id': event['id']})
    config = response.get('Item', {})

    return {
        'statusCode': 200,
        'body': json.dumps(config)
    }
```

When running locally, set the env var:
```bash
# For Moto — not needed, moto intercepts automatically
# For JAR — set before running tests
export DYNAMODB_ENDPOINT=http://localhost:8000
```
