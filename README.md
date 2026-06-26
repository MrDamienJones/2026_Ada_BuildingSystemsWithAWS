# Live Poll App — ADA Sheffield

A real-time audience-voting web application for a 2-hour L100 teaching session at ADA Sheffield. Apprentice learners vote on pre-seeded poll questions while the presenter demonstrates three AWS compute models (EC2, ECS Fargate, Lambda) hosting the same Python FastAPI backend.

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) | v2+ | Authenticate and interact with AWS |
| [AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html) | v2.260+ | Deploy infrastructure as code |
| [Python](https://www.python.org/downloads/) | 3.11+ | Backend application and CDK |
| [Docker](https://www.docker.com/get-started/) | Latest | Build container image for ECS stack |
| [Node.js](https://nodejs.org/) | 18+ | Required by AWS CDK CLI |

Ensure your AWS CLI is configured with credentials that have permission to create EC2, ECS, Lambda, DynamoDB, S3, CloudFront, and IAM resources in your target region (default: `eu-west-2`, configurable in `cdk/cdk_config.py`).

```bash
aws configure
# Set region to match your cdk_config.py (default: eu-west-2)
```

---

## Quick Start — Deployment

### 1. Install dependencies

```bash
cd adasheffield
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

**Expected outcome:** All packages install without errors. You now have FastAPI, CDK, Hypothesis, and boto3 available.

### 2. Configure CDK settings

```bash
copy cdk\cdk_config.example.py cdk\cdk_config.py
```

Edit `cdk/cdk_config.py` with your AWS account ID, region, and presenter secret key.

### 3. Bootstrap CDK (first time only)

```bash
cdk bootstrap aws://ACCOUNT_ID/eu-west-2
```

**Expected outcome:** CDK staging bucket and roles are created in your account. You see `Environment aws://ACCOUNT_ID/eu-west-2 bootstrapped`.

### 4. Deploy the Shared Stack

```bash
cdk deploy SharedStack
```

**Expected outcome:** DynamoDB tables are created. CDK outputs:

```
Outputs:
SharedStack.PollsTableName = live-poll-app
SharedStack.ConnectionsTableName = live-poll-connections
```

### 5. Deploy EC2 Stack

```bash
cdk deploy EC2Stack
```

**Expected outcome:** An Auto Scaling Group (t3.micro, min=1) is provisioned behind an Application Load Balancer. Python dependencies are installed via user data and the FastAPI app starts via systemd. CDK outputs:

```
Outputs:
EC2Stack.EC2AlbUrl = http://<EC2_ALB_DNS_NAME>
```

Verify: `curl http://<EC2_ALB_DNS_NAME>/health` → `{"status": "ok"}`

### 6. Deploy ECS Stack

```bash
cdk deploy ECSStack
```

**Expected outcome:** A Docker image is built and pushed to ECR. An ECS Fargate task starts behind an Application Load Balancer. CDK outputs:

```
Outputs:
ECSStack.AlbDnsName = http://<ALB_DNS_NAME>
```

Verify: `curl http://<ALB_DNS_NAME>/health` → `{"status": "ok"}`

### 7. Deploy Lambda Stack

```bash
cdk deploy LambdaStack
```

**Expected outcome:** Lambda functions and API Gateway (REST + WebSocket) are created. CDK outputs:

```
Outputs:
LambdaStack.RestApiUrl = https://<API_ID>.execute-api.eu-west-2.amazonaws.com/prod
LambdaStack.WebSocketApiUrl = wss://<WS_API_ID>.execute-api.eu-west-2.amazonaws.com/prod
```

Verify: `curl https://<API_ID>.execute-api.eu-west-2.amazonaws.com/prod/health` → `{"status": "ok"}`

### 8. Deploy Frontend Stack

```bash
cdk deploy FrontendStack
```

**Expected outcome:** Frontend files are deployed to S3 and served via CloudFront. CDK outputs:

```
Outputs:
FrontendStack.FrontendUrl = https://<DISTRIBUTION_ID>.cloudfront.net
```

Verify: Open the URL in a browser — you should see the Live Poll interface.

---

## Switching Backends

The frontend uses a **query parameter** (`?backend=`) to select which backend stack to connect to. No redeployment is needed during the session — students simply visit different URLs.

### How it works

| URL | Behaviour | Badge |
|-----|-----------|-------|
| `https://<CLOUDFRONT>/?backend=ec2` | Connects to EC2 ALB | ⚡ EC2 (Traditional) — orange |
| `https://<CLOUDFRONT>/?backend=ecs` | Connects to ECS ALB | 🐳 ECS (Container) — blue |
| `https://<CLOUDFRONT>/?backend=lambda` | Connects to Lambda API Gateway | λ Lambda (Serverless) — purple |
| `https://<CLOUDFRONT>/?backend=random` | Randomly picks one of the three | (varies) |
| `https://<CLOUDFRONT>/` (no param) | Falls back to `window.API_URL` default | (no badge) |

Each student sees a **coloured badge** in the header showing which backend they're connected to. All three backends share the same DynamoDB, so votes appear across all clients regardless of backend.

### Backend URL configuration

The `FrontendStack` automatically generates `frontend/config.js` at deploy time by reading backend URLs from SSM Parameter Store (written by each compute stack). You do **not** need to manually edit any HTML files — just deploy the compute stacks first, then deploy `FrontendStack`:

```bash
cdk deploy SharedStack EC2Stack ECSStack LambdaStack
cdk deploy FrontendStack
```

If you redeploy a compute stack and its URL changes, redeploy `FrontendStack` to pick up the new values.

### QR codes for the session

Pre-generate 4 QR codes pointing to your CloudFront URL with different query params:

1. **EC2:** `https://<CLOUDFRONT>/?backend=ec2`
2. **ECS:** `https://<CLOUDFRONT>/?backend=ecs`
3. **Lambda:** `https://<CLOUDFRONT>/?backend=lambda`
4. **Random:** `https://<CLOUDFRONT>/?backend=random`

Show individual QR codes when demonstrating each stack, or show the "random" code to split the room across all three simultaneously.

### Presenter page

The presenter page also supports `?backend=` alongside `?key=`:

```
https://<CLOUDFRONT>/presenter.html?key=YOUR_SECRET_KEY&backend=ec2
```

---

## Running Locally

### Start the backend

```bash
uvicorn app.main:app --port 8000
```

**Expected outcome:** Server starts at `http://localhost:8000`. Requires a local DynamoDB instance or AWS credentials configured for a remote table.

### Open the frontend

Open `frontend/index.html` directly in a browser. The default `window.API_URL` is already set to `http://localhost:8000`.

### Access the presenter page

Open `frontend/presenter.html?key=YOUR_SECRET_KEY` in a browser (use the `PRESENTER_SECRET_KEY` value from your `cdk/cdk_config.py`).

---

## Tear Down

Destroy stacks in reverse order. The shared stack's DynamoDB tables use a RETAIN deletion policy, so they will not be deleted even if the shared stack is destroyed.

### 1. Destroy Lambda Stack

```bash
cdk destroy LambdaStack
```

**Expected outcome:** Lambda functions, API Gateway endpoints, and associated IAM roles are deleted.

### 2. Destroy ECS Stack

```bash
cdk destroy ECSStack
```

**Expected outcome:** ECS service, Fargate task, ALB, and ECR repository are deleted.

### 3. Destroy EC2 Stack

```bash
cdk destroy EC2Stack
```

**Expected outcome:** Auto Scaling Group, EC2 instances, ALB, and security groups are deleted.

### 4. Destroy Frontend Stack

```bash
cdk destroy FrontendStack
```

**Expected outcome:** S3 bucket contents and CloudFront distribution are deleted.

### 5. Destroy Shared Stack

```bash
cdk destroy SharedStack
```

**Expected outcome:** Stack is deleted but DynamoDB tables are retained (RETAIN deletion policy). To fully remove them, delete the tables manually via the AWS Console or CLI:

```bash
aws dynamodb delete-table --table-name live-poll-app --region eu-west-2
aws dynamodb delete-table --table-name live-poll-connections --region eu-west-2
```

---

## Project Structure

```
adasheffield/
├── app/                        # FastAPI backend (shared across all stacks)
│   ├── main.py                 # App factory, router registration
│   ├── config.py               # Environment variable settings
│   ├── db/                     # DynamoDB client and query helpers
│   ├── models/                 # Pydantic models (Poll, Vote, etc.)
│   ├── routers/                # API route handlers
│   └── services/               # Business logic and broadcast abstraction
├── cdk/                        # CDK infrastructure stacks
│   ├── app.py                  # CDK app entry point
│   ├── cdk_config.example.py   # Configuration template (committed)
│   ├── cdk_config.py           # Your local config (gitignored)
│   ├── shared_stack.py         # DynamoDB tables (retain on delete)
│   ├── ec2_stack.py            # EC2 + ALB + Auto Scaling Group + systemd
│   ├── ecs_stack.py            # ECS Fargate + ALB + ECR
│   ├── lambda_stack.py         # Lambda + API Gateway (REST + WS)
│   ├── frontend_stack.py       # S3 + CloudFront frontend hosting
│   ├── custom_constructs/      # Reusable CDK constructs (seeder)
│   └── seed_data/              # Pre-seeded poll questions (polls.json)
├── lambda_handlers/            # Lambda entry points for API Gateway
├── frontend/                   # Static SPA (HTML/CSS/JS, no build step)
│   ├── index.html              # Participant voting page
│   ├── presenter.html          # Presenter control page
│   ├── app.js                  # Participant app logic
│   ├── presenter.js            # Presenter control logic
│   └── style.css               # Responsive styles
├── tests/                      # Unit, property-based, and integration tests
├── Dockerfile                  # Container image for ECS stack
├── cdk.json                    # CDK project configuration
└── requirements.txt            # Python dependencies
```

---

## Environment Variables

| Variable | Required by | Description |
|----------|-------------|-------------|
| `DYNAMODB_TABLE` | All stacks | Main DynamoDB table name (`live-poll-app`) |
| `CONNECTIONS_TABLE` | Lambda only | WebSocket connections table name |
| `PRESENTER_SECRET_KEY` | All stacks | Secret key for presenter page authentication |
| `WS_ENDPOINT_URL` | Lambda only | API Gateway Management API endpoint for broadcasts |
| `AWS_REGION` | All stacks | AWS region (`eu-west-2`) |

---

## Useful Commands

| Command | Description |
|---------|-------------|
| `cdk synth` | Generate CloudFormation templates without deploying |
| `cdk diff EC2Stack` | Preview changes before deploying a stack |
| `cdk list` | List all defined stacks |
| `pytest tests/` | Run all tests (unit + property-based) |
| `pytest tests/unit/` | Run unit and property-based tests only |
