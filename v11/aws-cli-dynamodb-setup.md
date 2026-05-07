# AWS CLI Setup & DynamoDB Access Troubleshooting Guide

A step-by-step guide for installing the AWS CLI, configuring it, and troubleshooting why an IAM user can access DynamoDB through the console but not via the CLI.

---

## The Core Issue

If a user can view DynamoDB tables in the console but not via the CLI, this is **not normal** when permissions are correct. The most common causes are:

1. **Region mismatch** — CLI configured for a different region than where the tables live
2. **Wrong credentials** — CLI authenticated as a different user than the console
3. **MFA enforcement** — Policy requires MFA, which the CLI doesn't satisfy automatically
4. **Conditional policies** — SCPs, permission boundaries, or IP restrictions blocking CLI calls

---

## Step 1: Install the AWS CLI

### macOS

```bash
curl "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o "AWSCLIV2.pkg"
sudo installer -pkg AWSCLIV2.pkg -target /
```

Or with Homebrew:

```bash
brew install awscli
```

### Linux

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
```

### Windows

Download and run the MSI installer from:
`https://awscli.amazonaws.com/AWSCLIV2.msi`

### Verify installation

```bash
aws --version
```

You should see something like `aws-cli/2.x.x`.

---

## Step 2: Get Your Credentials from the AWS Console

### Access Key ID and Secret Access Key

1. Sign in to the AWS Console at `https://console.aws.amazon.com/`
2. In the search bar at the top, type **IAM** and click it
3. In the left sidebar, click **Users**
4. Click the username of the user who needs CLI access
5. Click the **Security credentials** tab
6. Scroll down to the **Access keys** section
7. Click **Create access key**
8. Select **Command Line Interface (CLI)** as the use case
9. Check the confirmation box and click **Next**
10. (Optional) Add a description tag, then click **Create access key**
11. On the final screen, you'll see:
    - **Access key** — your Access Key ID (starts with `AKIA...`)
    - **Secret access key** — click **Show** to reveal it

> **Important:** Download the `.csv` file or copy both values immediately. The secret access key is shown only once. If lost, you must delete the key and create a new one.

### Default Region Name

Find this from the top-right of the AWS Console, next to your username. It shows the current region (e.g., "N. Virginia" = `us-east-1`).

Common region codes:

| Region | Code |
|--------|------|
| N. Virginia | `us-east-1` |
| Ohio | `us-east-2` |
| Oregon | `us-west-2` |
| Ireland | `eu-west-1` |
| Singapore | `ap-southeast-1` |

For DynamoDB: go to the DynamoDB console, confirm which region shows your tables, and use that region code.

### Default Output Format

Just use `json`. Other options are `text`, `table`, or `yaml`.

---

## Step 3: Configure the CLI

Run:

```bash
aws configure
```

You'll be prompted for four values:

```
AWS Access Key ID [None]: AKIA....................
AWS Secret Access Key [None]: ........................................
Default region name [None]: us-east-1
Default output format [None]: json
```

This writes to `~/.aws/credentials` and `~/.aws/config`.

---

## Step 4: Verify Your Identity

Before testing DynamoDB, confirm the CLI knows who it is:

```bash
aws sts get-caller-identity
```

You should see something like:

```json
{
    "UserId": "AIDAEXAMPLE...",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/your-username"
}
```

**Confirm the ARN matches the user you expect.** This is the single most useful sanity check.

---

## Step 5: Test DynamoDB Access

```bash
aws dynamodb list-tables
```

### Possible outcomes

**Empty list returned:**

```json
{ "TableNames": [] }
```

You're likely in the wrong region. Try explicitly:

```bash
aws dynamodb list-tables --region us-east-1
```

**AccessDeniedException:**

This is a permissions issue — proceed to Step 6.

**Tables listed successfully:**

You're done! Test further with:

```bash
aws dynamodb describe-table --table-name YourTableName
```

---

## Step 6: Check IAM Permissions

In the console, go to **IAM → Users → [your user] → Permissions**.

### Minimum policy for read access

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:ListTables",
        "dynamodb:DescribeTable",
        "dynamodb:Scan",
        "dynamodb:Query",
        "dynamodb:GetItem"
      ],
      "Resource": "*"
    }
  ]
}
```

### Quick fix for testing

Attach the AWS managed policy `AmazonDynamoDBFullAccess` via **Add permissions → Attach policies directly**.

### Things to inspect while in IAM

- **Permission boundary** on the user — if set, it caps what the user can do regardless of attached policies. A user with `FullAccess` attached can still be blocked by a boundary that doesn't allow DynamoDB.
- **SCPs (Service Control Policies)** at the AWS Organizations level — if your account is part of an org, an SCP in the management account could deny DynamoDB calls.
- **Policy conditions** — open each attached policy and look for `Condition` blocks. Common gotchas:
  - `aws:SourceIp` — your CLI's IP isn't in the allowed list
  - `aws:MultiFactorAuthPresent: true` — the CLI session doesn't have MFA
  - `aws:RequestedRegion` — only certain regions are allowed

---

## Step 7: Handle MFA (If Required)

The console satisfies MFA at sign-in. The CLI does not, unless you explicitly get session tokens.

### Get temporary credentials with MFA

```bash
aws sts get-session-token \
  --serial-number arn:aws:iam::ACCOUNT_ID:mfa/USERNAME \
  --token-code 123456 \
  --duration-seconds 3600
```

Replace:
- `ACCOUNT_ID` with your AWS account ID
- `USERNAME` with the IAM username
- `123456` with the current code from your MFA device

### Use the temporary credentials

The output gives you `AccessKeyId`, `SecretAccessKey`, and `SessionToken`. Export them:

```bash
export AWS_ACCESS_KEY_ID=ASIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_SESSION_TOKEN=...
```

Then retry your DynamoDB call.

---

## Step 8: Decode AccessDenied Errors

If you're still getting `AccessDeniedException`, AWS includes an encoded message that reveals the exact reason:

```bash
aws sts decode-authorization-message --encoded-message <encoded-message-here>
```

This requires `sts:DecodeAuthorizationMessage` permission, but it tells you precisely which policy and condition denied the call.

---

## Quick Diagnostic Checklist

When the console works but the CLI doesn't, run through these in order:

- [ ] `aws --version` — CLI installed?
- [ ] `aws sts get-caller-identity` — correct user identity?
- [ ] `aws configure get region` — correct region?
- [ ] `aws dynamodb list-tables --region <correct-region>` — works with explicit region?
- [ ] IAM permissions include DynamoDB actions?
- [ ] Any permission boundary on the user?
- [ ] Any SCPs at the org level?
- [ ] Any policy conditions (IP, MFA, region) blocking the call?
- [ ] If MFA required, are you using session tokens?

---

## Useful Reference Commands

```bash
# Show currently configured profile
aws configure list

# Use a specific profile
aws dynamodb list-tables --profile myprofile

# Set profile via environment
export AWS_PROFILE=myprofile

# Check the region currently set
aws configure get region

# List all configured profiles
aws configure list-profiles

# Test connectivity with verbose debug output
aws dynamodb list-tables --debug
```
