"""Shared CDK stack defining DynamoDB tables for the Live Poll App."""

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from constructs import Construct


class SharedStack(Stack):
    """Shared resources used across EC2, ECS, and Lambda stacks.

    Defines the DynamoDB main table and connections table with DESTROY
    deletion policy for easy teardown of this classroom demo app.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Main table: live-poll-app (single-table design with composite key)
        self.main_table = dynamodb.Table(
            self,
            "MainTable",
            table_name="live-poll-app",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            removal_policy=RemovalPolicy.DESTROY,
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )

        # Connections table: live-poll-connections (Lambda WebSocket state)
        self.connections_table = dynamodb.Table(
            self,
            "ConnectionsTable",
            table_name="live-poll-connections",
            partition_key=dynamodb.Attribute(
                name="connection_id", type=dynamodb.AttributeType.STRING
            ),
            removal_policy=RemovalPolicy.DESTROY,
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
        )

        # Stack outputs — used by compute stacks to reference table resources
        CfnOutput(self, "MainTableName", value=self.main_table.table_name)
        CfnOutput(self, "MainTableArn", value=self.main_table.table_arn)
        CfnOutput(self, "ConnectionsTableName", value=self.connections_table.table_name)
        CfnOutput(self, "ConnectionsTableArn", value=self.connections_table.table_arn)
