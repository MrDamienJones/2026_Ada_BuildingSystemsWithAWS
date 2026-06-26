# AWS Architecture Diagram — Live Poll App

> **Editable diagram with AWS icons:** Open [`architecture.drawio`](./architecture.drawio) in [draw.io](https://app.diagrams.net) or the VS Code Draw.io Integration extension. The file uses the official `mxgraph.aws4` icon library.

## High-Level Architecture

```mermaid
flowchart TB
    %% Users
    participant["👤 Participant\n(Browser)"]
    presenter["🎤 Presenter\n(Browser)"]

    %% Frontend Hosting
    subgraph Frontend["Frontend Hosting (FrontendStack)"]
        CF["☁️ CloudFront\nDistribution\n(HTTPS, OAC)"]
        CFF["CloudFront Function\n(Strip /ec2-api, /ecs-api prefix)"]
        S3["🪣 S3 Bucket\n(Block Public Access)\nStatic SPA"]
    end

    %% Compute Stacks
    subgraph Compute["Three Compute Models (same FastAPI app)"]
        direction TB

        subgraph EC2_Stack["EC2Stack — Traditional"]
            EC2ALB["⚖️ Application\nLoad Balancer\n(Port 80)"]
            ASG["📈 Auto Scaling Group\n(min=1, max=3)"]
            EC2["💻 EC2 t3.micro\n(Amazon Linux 2023)\nsystemd + uvicorn"]
            SG["🔒 Security Groups\n(ALB + Instance)"]
            EC2Role["IAM Role\n(DynamoDB + SSM)"]
            S3Asset["📦 S3 Asset\n(App Code)"]
        end

        subgraph ECS_Stack["ECSStack — Containerised"]
            ALB["⚖️ Application\nLoad Balancer\n(Port 80)"]
            Fargate["🐳 Fargate Task\n512 CPU / 1024 MB\n(Docker + uvicorn)"]
            ECSCluster["ECS Cluster\n(Default VPC)"]
        end

        subgraph Lambda_Stack["LambdaStack — Serverless"]
            APIGW_REST["🌐 API Gateway\nREST API\n(Proxy Integration)"]
            APIGW_WS["🔌 API Gateway\nWebSocket API\n($connect/$disconnect/$default)"]
            RestLambda["λ REST Lambda\n(Mangum + FastAPI)\n256 MB"]
            WSLambda["λ WebSocket Lambda\n(Lifecycle Handler)\n128 MB"]
        end
    end

    %% Shared Data Layer
    subgraph Shared["SharedStack — Data Layer"]
        MainTable["📊 DynamoDB\nlive-poll-app\n(PK/SK, PAY_PER_REQUEST)"]
        ConnTable["🔗 DynamoDB\nlive-poll-connections\n(TTL-enabled)"]
    end

    %% Cross-Stack Coordination
    subgraph Config["Cross-Stack Coordination"]
        SSM["🔑 SSM Parameter Store\n/live-poll/ec2-url\n/live-poll/ecs-url\n/live-poll/lambda-url\n/live-poll/lambda-ws-url"]
    end

    %% Connections — Users to Frontend
    participant --> CF
    presenter --> CF

    %% CloudFront to Origins
    CF --> S3
    CF -- "/ec2-api/*" --> CFF
    CF -- "/ecs-api/*" --> CFF
    CFF --> EC2ALB
    CFF --> ALB

    %% EC2 Stack Flow
    EC2ALB --> ASG
    ASG --> EC2
    EC2 --> MainTable
    S3Asset -.-> EC2

    %% ECS Stack Flow
    ALB --> Fargate
    Fargate --> MainTable

    %% Lambda Stack Flow
    CF -- "REST API (direct)" --> APIGW_REST
    participant -- "WSS" --> APIGW_WS
    APIGW_REST --> RestLambda
    APIGW_WS --> WSLambda
    RestLambda --> MainTable
    RestLambda --> ConnTable
    WSLambda --> ConnTable
    RestLambda -- "ManageConnections API" --> APIGW_WS

    %% SSM reads at synth
    SSM -.->|"read at cdk synth"| CF
```

## Data Flow — Vote Lifecycle

```mermaid
sequenceDiagram
    participant User as 👤 Participant
    participant CF as CloudFront
    participant BE as Backend (EC2/ECS/Lambda)
    participant DB as DynamoDB (live-poll-app)
    participant WS as WebSocket (all clients)

    User->>CF: POST /polls/{id}/votes
    CF->>BE: Forward request
    BE->>DB: PutItem (vote record)
    DB-->>BE: Success
    BE->>DB: Query (aggregated results)
    DB-->>BE: Updated counts
    BE->>WS: Broadcast {poll_id, results}
    WS->>User: Real-time bar chart update
```

## Stack Dependency Map

```mermaid
flowchart LR
    Shared["SharedStack\n(DynamoDB Tables)"]
    EC2["EC2Stack"]
    ECS["ECSStack"]
    Lambda["LambdaStack"]
    Frontend["FrontendStack"]

    Shared --> EC2
    Shared --> ECS
    Shared --> Lambda
    EC2 -->|SSM param| Frontend
    ECS -->|SSM param| Frontend
    Lambda -->|SSM param| Frontend
```

## Service Inventory

| AWS Service | Stack | Purpose |
|---|---|---|
| **DynamoDB** | SharedStack | Main data store (polls, votes) + WebSocket connections |
| **EC2** | EC2Stack | Traditional compute (t3.micro, Amazon Linux 2023) |
| **ALB** | EC2Stack | Application Load Balancer (port 80 → instance 80) |
| **Auto Scaling Group** | EC2Stack | Min 1, max 3 instances with health checks |
| **Security Groups** | EC2Stack | ALB (public HTTP) + Instance (ALB-only HTTP) |
| **IAM Role** | EC2Stack | EC2 instance profile (DynamoDB + SSM access) |
| **S3 Asset** | EC2Stack | Application code bundle uploaded to S3 |
| **ECS Fargate** | ECSStack | Container compute (512 CPU / 1024 MB) |
| **ALB** | ECSStack | Load balancer (port 80 → container 8000) |
| **ECR** | ECSStack | Docker image registry (via `from_asset`) |
| **Lambda** | LambdaStack | REST handler (Mangum) + WebSocket handler |
| **API Gateway REST** | LambdaStack | HTTPS proxy to REST Lambda |
| **API Gateway WebSocket** | LambdaStack | WSS connection lifecycle management |
| **S3** | FrontendStack | Static SPA hosting (private, OAC) |
| **CloudFront** | FrontendStack | CDN, HTTPS termination, API proxying |
| **CloudFront Functions** | FrontendStack | URL prefix stripping for EC2/ECS proxy |
| **SSM Parameter Store** | All compute + Frontend | Cross-stack URL sharing |

## Region & Account

- **Region:** `eu-west-2` (London) — configurable in `cdk/cdk_config.py`
- **Account:** Set in `cdk/cdk_config.py` (not committed to source control)
