"""CDK assertion tests for the Live Poll App infrastructure stacks.

Validates: Requirements 10.1, 10.2, 7.3, 8.3, 9.1, 10.4

Tests cover:
- SharedStack: DynamoDB tables with DELETE deletion policy (demo app)
- LambdaStack: Lambda function handlers and CDK outputs

Uses aws_cdk.assertions for template-level verification.
"""

import os
import sys
from unittest.mock import patch

import pytest

# Add the cdk directory to the path so we can import the stacks
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "cdk"))

import aws_cdk as cdk
from aws_cdk import aws_lambda as _lambda
from aws_cdk.assertions import Match, Template

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    """Create a fresh CDK app for each test."""
    return cdk.App()


@pytest.fixture
def shared_stack(app):
    """Create and return the SharedStack for testing."""
    from shared_stack import SharedStack

    return SharedStack(app, "TestSharedStack")


@pytest.fixture
def shared_template(shared_stack):
    """Return the synthesized template for SharedStack."""
    return Template.from_stack(shared_stack)


@pytest.fixture
def lambda_stack(app, shared_stack, tmp_path):
    """Create and return the LambdaStack for testing.

    Patches Code.from_asset to use a minimal temporary directory instead of
    the full project root, avoiding slow asset bundling during tests.
    """
    from lambda_stack import LambdaStack

    # Create a minimal placeholder file so the asset directory isn't empty
    placeholder = tmp_path / "handler.py"
    placeholder.write_text("# placeholder for CDK asset bundling in tests\n")

    with patch.object(_lambda.Code, "from_asset", return_value=_lambda.Code.from_inline("# test")):
        return LambdaStack(app, "TestLambdaStack", shared_stack=shared_stack)


@pytest.fixture
def lambda_template(lambda_stack):
    """Return the synthesized template for LambdaStack."""
    return Template.from_stack(lambda_stack)


# ---------------------------------------------------------------------------
# SharedStack Tests
# ---------------------------------------------------------------------------


class TestSharedStack:
    """Tests for the SharedStack (DynamoDB tables)."""

    def test_shared_stack_has_two_dynamodb_tables(self, shared_template):
        """SharedStack defines exactly 2 DynamoDB tables."""
        shared_template.resource_count_is("AWS::DynamoDB::Table", 2)

    def test_main_table_has_delete_deletion_policy(self, shared_template):
        """Main DynamoDB table has DeletionPolicy: Delete (demo app, easy teardown)."""
        shared_template.has_resource(
            "AWS::DynamoDB::Table",
            {
                "DeletionPolicy": "Delete",
                "Properties": Match.object_like(
                    {
                        "TableName": "live-poll-app",
                    }
                ),
            },
        )

    def test_connections_table_has_delete_deletion_policy(self, shared_template):
        """Connections DynamoDB table has DeletionPolicy: Delete (demo app, easy teardown)."""
        shared_template.has_resource(
            "AWS::DynamoDB::Table",
            {
                "DeletionPolicy": "Delete",
                "Properties": Match.object_like(
                    {
                        "TableName": "live-poll-connections",
                    }
                ),
            },
        )

    def test_main_table_has_composite_key(self, shared_template):
        """Main table uses PK (partition) and SK (sort) composite key."""
        shared_template.has_resource_properties(
            "AWS::DynamoDB::Table",
            Match.object_like(
                {
                    "TableName": "live-poll-app",
                    "KeySchema": [
                        {"AttributeName": "PK", "KeyType": "HASH"},
                        {"AttributeName": "SK", "KeyType": "RANGE"},
                    ],
                }
            ),
        )

    def test_connections_table_has_ttl(self, shared_template):
        """Connections table has TTL enabled on the 'ttl' attribute."""
        shared_template.has_resource_properties(
            "AWS::DynamoDB::Table",
            Match.object_like(
                {
                    "TableName": "live-poll-connections",
                    "TimeToLiveSpecification": {
                        "AttributeName": "ttl",
                        "Enabled": True,
                    },
                }
            ),
        )

    def test_shared_stack_outputs_table_names(self, shared_template):
        """SharedStack exports table name and ARN outputs."""
        shared_template.has_output("MainTableName", {})
        shared_template.has_output("MainTableArn", {})
        shared_template.has_output("ConnectionsTableName", {})
        shared_template.has_output("ConnectionsTableArn", {})


# ---------------------------------------------------------------------------
# LambdaStack Tests
# ---------------------------------------------------------------------------


class TestLambdaStack:
    """Tests for the LambdaStack (Lambda functions + API Gateway)."""

    def test_rest_lambda_has_correct_handler(self, lambda_template):
        """REST Lambda function uses lambda_handlers.polls.handler."""
        lambda_template.has_resource_properties(
            "AWS::Lambda::Function",
            Match.object_like(
                {
                    "Handler": "lambda_handlers.polls.handler",
                    "Runtime": "python3.11",
                }
            ),
        )

    def test_websocket_lambda_has_correct_handler(self, lambda_template):
        """WebSocket Lambda function uses lambda_handlers.websocket.handler."""
        lambda_template.has_resource_properties(
            "AWS::Lambda::Function",
            Match.object_like(
                {
                    "Handler": "lambda_handlers.websocket.handler",
                    "Runtime": "python3.11",
                }
            ),
        )

    def test_lambda_stack_has_rest_api(self, lambda_template):
        """LambdaStack defines an API Gateway REST API."""
        lambda_template.resource_count_is("AWS::ApiGateway::RestApi", 1)

    def test_lambda_stack_has_websocket_api(self, lambda_template):
        """LambdaStack defines an API Gateway WebSocket API."""
        lambda_template.has_resource_properties(
            "AWS::ApiGatewayV2::Api",
            Match.object_like(
                {
                    "ProtocolType": "WEBSOCKET",
                }
            ),
        )

    def test_lambda_stack_outputs_rest_api_url(self, lambda_template):
        """LambdaStack outputs the REST API URL."""
        lambda_template.has_output("RestApiUrl", {})

    def test_lambda_stack_outputs_websocket_api_url(self, lambda_template):
        """LambdaStack outputs the WebSocket API URL."""
        lambda_template.has_output("WebSocketApiUrl", {})

    def test_rest_lambda_has_dynamodb_table_env_var(self, lambda_template):
        """REST Lambda has DYNAMODB_TABLE environment variable."""
        lambda_template.has_resource_properties(
            "AWS::Lambda::Function",
            Match.object_like(
                {
                    "Handler": "lambda_handlers.polls.handler",
                    "Environment": {
                        "Variables": Match.object_like(
                            {
                                "DYNAMODB_TABLE": Match.any_value(),
                            }
                        )
                    },
                }
            ),
        )

    def test_websocket_lambda_has_connections_table_env_var(self, lambda_template):
        """WebSocket Lambda has CONNECTIONS_TABLE environment variable."""
        lambda_template.has_resource_properties(
            "AWS::Lambda::Function",
            Match.object_like(
                {
                    "Handler": "lambda_handlers.websocket.handler",
                    "Environment": {
                        "Variables": Match.object_like(
                            {
                                "CONNECTIONS_TABLE": Match.any_value(),
                            }
                        )
                    },
                }
            ),
        )
