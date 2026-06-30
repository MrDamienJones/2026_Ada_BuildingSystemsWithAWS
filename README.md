# Live Poll App — ADA Sheffield

A real-time audience-voting web application for a 2-hour L100 teaching session at ADA Sheffield. Apprentice learners vote on pre-seeded poll questions while the presenter demonstrates three AWS compute models (EC2, ECS Fargate, Lambda) hosting the same Python FastAPI backend.

---

## Table of Contents

- [AWS Services Used](#aws-services-used)
- [Prerequisites](#prerequisites)
- [Quick Start — Deployment](#quick-start--deployment)
- [Switching Backends](#switching-backends)
- [Development](#development)
  - [Running locally](#running-locally)
  - [Pre-commit hooks](#pre-commit-hooks)
  - [Useful commands](#useful-commands)
- [Tear Down](#tear-down)
- [Project Structure](#project-structure)
- [Environment Variables](#environment-variables)
- [Compute Tradeoffs — EC2 vs ECS vs Lambda](#compute-tradeoffs--ec2-vs-ecs-vs-lambda)
- [Session Reference Links](#session-reference-links)

---

## AWS Services Used

| AWS Service | What It Does | Role in This Project |
|-------------|--------------|----------------------|
| **Amazon EC2** | Virtual machines in the cloud | Hosts the FastAPI backend on t3.micro instances behind an Auto Scaling Group — demonstrates the traditional compute model |
| **Elastic Load Balancing (ALB)** | Distributes incoming traffic across multiple targets | Provides a stable HTTP endpoint in front of EC2 and ECS instances; performs health checks |
| **Auto Scaling** | Automatically adjusts compute capacity | Scales EC2 instances between 1–3 based on demand |
| **Amazon ECS (Fargate)** | Run containers without managing servers | Hosts the same FastAPI backend as a Docker container — demonstrates the container compute model |
| **Amazon ECR** | Private Docker container registry | Stores the Docker image built by CDK for the ECS Fargate task |
| **AWS Lambda** | Run code without provisioning servers | Hosts the FastAPI backend (via Mangum) and WebSocket handler — demonstrates the serverless compute model |
| **Amazon API Gateway (REST)** | Managed REST API endpoint | Routes HTTP requests to the REST Lambda function with a proxy integration |
| **Amazon API Gateway (WebSocket)** | Managed WebSocket API endpoint | Handles real-time connections ($connect/$disconnect/$default) for live vote broadcasting |
| **Amazon DynamoDB** | Serverless NoSQL database | Stores poll questions, vote tallies, and WebSocket connection state (shared across all three compute stacks) |
| **Amazon S3** | Object storage | Hosts the static frontend files (HTML/CSS/JS) and stores the EC2 application code asset |
| **Amazon CloudFront** | Content delivery network (CDN) | Serves the frontend over HTTPS globally; proxies EC2/ECS API calls to avoid mixed-content issues |
| **AWS Systems Manager (SSM)** | Parameter store and instance management | Stores backend URLs so the FrontendStack can generate `config.js` at deploy time; enables Session Manager on EC2 |
| **AWS IAM** | Identity and access management | Grants each compute stack least-privilege DynamoDB access; defines service roles for EC2, ECS, and Lambda |
| **AWS CloudFormation** | Infrastructure as code deployment engine | Underlying service that CDK synthesises templates for; manages stack creation, updates, and deletion |
| **AWS CDK (Cloud Development Kit)** | High-level IaC framework (Python) | Defines all infrastructure in Python; synthesises to CloudFormation and handles asset bundling/deployment |

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

## Development

### Running locally

```bash
uvicorn app.main:app --port 8000
```

**Expected outcome:** Server starts at `http://localhost:8000`. Requires a local DynamoDB instance or AWS credentials configured for a remote table.

Open `frontend/index.html` directly in a browser. The default `window.API_URL` is already set to `http://localhost:8000`.

To access the presenter page, open `frontend/presenter.html?key=YOUR_SECRET_KEY` in a browser (use the `PRESENTER_SECRET_KEY` value from your `cdk/cdk_config.py`).

### Pre-commit hooks

This project uses [pre-commit](https://pre-commit.com/) to run automated checks before every commit. This catches common issues (formatting, secrets, broken YAML) before they reach the repository.

```bash
pip install pre-commit
pre-commit install
```

After running `pre-commit install`, the hooks will run automatically on every `git commit`. You only need to do this once per clone.

| Hook | Source | Purpose |
|------|--------|---------|
| `trailing-whitespace` | pre-commit-hooks | Strips trailing whitespace from all files |
| `end-of-file-fixer` | pre-commit-hooks | Ensures files end with a single newline |
| `check-yaml` | pre-commit-hooks | Validates YAML syntax |
| `check-json` | pre-commit-hooks | Validates JSON syntax |
| `check-added-large-files` | pre-commit-hooks | Blocks files over 500 KB (prevents accidental binary commits) |
| `detect-private-key` | pre-commit-hooks | Catches accidentally committed private keys |
| `check-merge-conflict` | pre-commit-hooks | Flags unresolved merge conflict markers |
| `ruff` | ruff-pre-commit | Lints Python code and auto-fixes issues |
| `ruff-format` | ruff-pre-commit | Formats Python code (Black-compatible) |
| `detect-secrets` | Yelp/detect-secrets | Scans for hardcoded secrets, tokens, and passwords |

The `detect-secrets` and `detect-private-key` hooks are particularly important — they act as a safety net preventing AWS credentials, API keys, or the presenter secret from being accidentally committed. Combined with the `.gitignore` rules, this gives two layers of protection against sensitive data leaking into version control.

To run all hooks against every file (not just staged changes):

```bash
pre-commit run --all-files
```

To update hooks to their latest versions:

```bash
pre-commit autoupdate
```

### Useful commands

| Command | Description |
|---------|-------------|
| `cdk synth` | Generate CloudFormation templates without deploying |
| `cdk diff EC2Stack` | Preview changes before deploying a stack |
| `cdk list` | List all defined stacks |
| `pytest tests/` | Run all tests (unit + property-based) |
| `pytest tests/unit/` | Run unit and property-based tests only |
| `pre-commit run --all-files` | Run all pre-commit hooks against the entire repo |

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

## Compute Tradeoffs — EC2 vs ECS vs Lambda

This session uses three AWS compute models to host the same FastAPI backend. Each represents a different point on the control-versus-convenience spectrum, and none of them is universally "best" — it's all about tradeoffs.

### Cost Comparison

| Service | Approx. Monthly Cost (light usage) | What You're Paying For |
|---------|-------------------------------------|------------------------|
| Lambda | ~£0–2 | Per-invocation only; free tier covers 1M requests |
| EC2 + ALB | ~£24–30 | ALB (~£16) + t3.micro (~£8) running 24/7 |
| ECS Fargate + ALB | ~£30–40 | ALB (~£16) + Fargate vCPU/memory (~£14–24) 24/7 |

ECS Fargate is the most expensive of the three implementations. The premium comes from AWS managing the underlying instances for you — you never need to SSH into a host, never patch a kernel, never worry about capacity planning at the VM level.

EC2 is still the right fit if you need full OS access or custom networking, have legacy apps that can't be containerised, or use existing tooling built around SSH/Ansible.

### EC2 — The Virtual Machine

| | |
|---|---|
| ✅ Full control over the OS, runtime, and networking | ❌ You patch the OS, manage security groups, configure firewalls |
| ✅ Easiest mental model — it's just a virtual machine | ❌ Always running — paying 24/7 whether anyone is using the app or not |
| ✅ Portable between cloud providers (any VM host works the same way) | |

EC2 gives you the most control but the most responsibility.

### ECS Fargate — The Container

| | |
|---|---|
| ✅ No OS patching — AWS manages the host underneath | ❌ More abstraction layers to understand (tasks, services, clusters, target groups) |
| ✅ Scales horizontally by adding more containers | ❌ Still "always on" unless you configure scale-to-zero (which isn't straightforward) |
| ✅ Container image is portable — runs the same on your laptop as in AWS | ❌ Slower deployments — rolling out a new container image takes 2–5 minutes |

Docker-related safety measures (image scanning, read-only filesystems, non-root users) take longer to configure up front, but the resulting container stands up to more scrutiny than a bare EC2 instance with a script-based deploy.

### Lambda — The Function

| | |
|---|---|
| ✅ Cheapest at low/moderate traffic — free tier covers 1M requests/month | ❌ Hard limits: 15-min max execution, 10 GB memory, 6 MB response payload |
| ✅ Pay only when code executes (true pay-per-use) | ❌ Architecturally bound to AWS (not portable without significant rework) |
| ✅ AWS manages everything: scaling, patching, availability | ❌ Harder to test locally |
| ✅ Scales to hundreds of concurrent executions automatically | |

Lambda shifts almost all operational responsibility to AWS. The tradeoff is flexibility — you accept hard runtime limits and tight coupling to the AWS ecosystem.

### The Pattern

As you move from EC2 → ECS → Lambda:

- **You give up control** — less access to the OS, fewer knobs to turn
- **You gain convenience** — less patching, less capacity planning, less ops burden
- **The responsibility boundary shifts** — more of the Shared Responsibility Model falls on AWS's side
- **Portability decreases** — EC2 workloads move easily between clouds; Lambda functions are deeply AWS-native

There is no single right answer. The choice depends on the workload, the team's skills, the budget, and how much operational overhead you're willing to accept.

---

## Session Reference Links

The following AWS resources were used during the live session to support key teaching points about the scale, breadth, and responsibility model of cloud computing.

### Scale of AWS

- **[AWS Service Health Dashboard](https://health.aws.amazon.com/health/status)** — Used to demonstrate the number of AWS services via the volume of pages listed on the status dashboard. Gives learners an immediate visual sense of how large the platform is.

### Global Infrastructure

- **[AWS Regions & Availability Zones](https://aws.amazon.com/about-aws/global-infrastructure/regions_az/)** — Used to show the worldwide distribution of AWS Regions, Availability Zones, and Edge Locations. Reinforces that AWS operates physical infrastructure across the globe, not just "somewhere in the cloud."

### AWS Service Categories

These pages were used to show specific AWS services grouped by function, illustrating that each service solves a particular problem:

| Link | Category | Page Format |
|------|----------|-------------|
| [AWS Compute Services](https://aws.amazon.com/products/compute/) | Compute | Table |
| [AWS Storage Services](https://aws.amazon.com/products/storage/) | Storage | Cards |
| [AWS Database Services](https://aws.amazon.com/products/databases/) | Databases | Table |
| [AWS AI/ML Services](https://aws.amazon.com/ai/services/) | AI & Machine Learning | Cards |

Each page demonstrates how AWS offers purpose-built services rather than one-size-fits-all solutions — learners can see the variety of options available within a single domain.

### Shared Responsibility Model

- **[AWS Shared Responsibility Model](https://aws.amazon.com/compliance/shared-responsibility-model/)** — Used to show where the boundary lies between what AWS manages (security *of* the cloud) and what the customer manages (security *in* the cloud). This directly ties into the session's comparison of EC2, ECS, and Lambda — as you move from EC2 to Lambda, more responsibility shifts to AWS.
