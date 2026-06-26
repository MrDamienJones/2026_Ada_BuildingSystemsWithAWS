"""ECS CDK stack deploying the Live Poll App on Fargate behind an ALB.

Builds a Docker image from the project root, deploys it to ECS Fargate
with an Application Load Balancer forwarding port 80 to container port 8000.
"""

import os

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
)
from aws_cdk import (
    aws_ec2 as ec2,
)
from aws_cdk import (
    aws_ecs as ecs,
)
from aws_cdk import (
    aws_ecs_patterns as ecs_patterns,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_ssm as ssm,
)
from cdk_config import AWS_REGION, PRESENTER_SECRET_KEY
from constructs import Construct


class ECSStack(Stack):
    """ECS Fargate stack for the Live Poll App.

    Deploys the FastAPI application as a Docker container on ECS Fargate
    with an internet-facing ALB. Grants DynamoDB access to the task role
    and triggers the seeder construct on deploy.

    Parameters
    ----------
    shared_stack : Stack
        The shared stack providing DynamoDB table references.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        shared_stack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Reference shared DynamoDB table
        table_name = shared_stack.main_table.table_name
        table_arn = shared_stack.main_table.table_arn

        # Use default VPC
        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)

        # ECS Cluster
        cluster = ecs.Cluster(self, "LivePollCluster", vpc=vpc)

        # Build Docker image from project root (where Dockerfile lives)
        project_root = os.path.join(os.path.dirname(__file__), "..")

        # Fargate service with ALB using the high-level pattern
        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "LivePollService",
            cluster=cluster,
            cpu=512,
            memory_limit_mib=1024,
            desired_count=1,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(project_root),
                container_port=8000,
                environment={
                    "DYNAMODB_TABLE": table_name,
                    "AWS_REGION": AWS_REGION,
                    "PRESENTER_SECRET_KEY": PRESENTER_SECRET_KEY,
                    "ALLOWED_ORIGINS": "*",
                },
            ),
            public_load_balancer=True,
            listener_port=80,
            assign_public_ip=True,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            min_healthy_percent=100,
        )

        # Configure health check on the target group
        fargate_service.target_group.configure_health_check(
            path="/health",
            interval=Duration.seconds(30),
            timeout=Duration.seconds(5),
            healthy_threshold_count=2,
            unhealthy_threshold_count=3,
            healthy_http_codes="200",
        )

        # Set health check grace period for container startup
        fargate_service.service.node.default_child.add_property_override(
            "HealthCheckGracePeriodSeconds", 60
        )

        # Grant DynamoDB read/write permissions to the task role
        fargate_service.task_definition.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                    "dynamodb:BatchGetItem",
                    "dynamodb:BatchWriteItem",
                ],
                resources=[
                    table_arn,
                    f"{table_arn}/index/*",
                ],
            )
        )

        # Store ECS ALB URL in SSM for the frontend stack to reference
        ssm.StringParameter(
            self,
            "EcsUrlParam",
            parameter_name="/live-poll/ecs-url",
            string_value="http://" + fargate_service.load_balancer.load_balancer_dns_name,
        )

        # Stack output: ALB DNS name
        CfnOutput(
            self,
            "AlbDnsName",
            value=fargate_service.load_balancer.load_balancer_dns_name,
            description="ALB DNS name for the ECS Live Poll App",
        )
