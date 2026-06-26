"""CDK Lambda stack for the Live Poll App.

Deploys Lambda functions behind API Gateway (REST + WebSocket) for the
serverless compute model. References the shared DynamoDB tables from
SharedStack.

Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.2, 10.4
"""

import os

import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
)
from aws_cdk import (
    aws_apigateway as apigw,
)
from aws_cdk import (
    aws_apigatewayv2 as apigwv2,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as _lambda,
)
from aws_cdk import (
    aws_ssm as _ssm,
)
from cdk_config import PRESENTER_SECRET_KEY
from constructs import Construct
from shared_stack import SharedStack

# Resolve project root (parent of cdk/)
PROJECT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


class LambdaStack(Stack):
    """Lambda + API Gateway stack for the Live Poll App.

    Creates:
    - REST Lambda function (Mangum handler for FastAPI routes)
    - WebSocket Lambda function (connection lifecycle management)
    - API Gateway REST API with proxy integration
    - API Gateway WebSocket API with $connect/$disconnect/$default routes
    - IAM permissions for DynamoDB and API Gateway Management API
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        shared_stack: SharedStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Shared table references
        main_table = shared_stack.main_table
        connections_table = shared_stack.connections_table

        # --- Lambda code asset with Docker bundling ---
        # Bundles app/ and lambda_handlers/ with pip dependencies installed.
        # Uses the project root as source but Docker only copies what's needed.
        code_asset = _lambda.Code.from_asset(
            path=PROJECT_ROOT,
            exclude=[
                ".venv",
                ".venv/**",
                "cdk",
                "cdk/**",
                "cdk.out",
                "cdk.out/**",
                "tests",
                "tests/**",
                "frontend",
                "frontend/**",
                ".kiro",
                ".kiro/**",
                ".hypothesis",
                ".hypothesis/**",
                ".pytest_cache",
                ".pytest_cache/**",
                ".vscode",
                ".vscode/**",
                "**/__pycache__",
                "**/__pycache__/**",
                "*.pyc",
                ".git",
                ".git/**",
                "node_modules",
                "node_modules/**",
                "Dockerfile",
                "*.md",
                ".cdkignore",
                "cdk.json",
                "brief.txt",
            ],
            bundling=cdk.BundlingOptions(
                image=_lambda.Runtime.PYTHON_3_11.bundling_image,
                command=[
                    "bash",
                    "-c",
                    "pip install -r lambda_requirements.txt -t /asset-output && "
                    "cp -au app /asset-output/app && "
                    "cp -au lambda_handlers /asset-output/lambda_handlers",
                ],
            ),
        )

        # --- REST Lambda Function (Mangum handler) ---
        self.rest_lambda = _lambda.Function(
            self,
            "RestLambda",
            function_name="live-poll-rest",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="lambda_handlers.polls.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "DYNAMODB_TABLE": main_table.table_name,
                "CONNECTIONS_TABLE": connections_table.table_name,
                "PRESENTER_SECRET_KEY": PRESENTER_SECRET_KEY,
                "ALLOWED_ORIGINS": "*",
            },
        )

        # --- WebSocket Lambda Function ---
        self.websocket_lambda = _lambda.Function(
            self,
            "WebSocketLambda",
            function_name="live-poll-websocket",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="lambda_handlers.websocket.handler",
            code=code_asset,
            timeout=Duration.seconds(10),
            memory_size=128,
            environment={
                "DYNAMODB_TABLE": main_table.table_name,
                "CONNECTIONS_TABLE": connections_table.table_name,
            },
        )

        # --- DynamoDB permissions for both functions ---
        main_table.grant_read_write_data(self.rest_lambda)
        main_table.grant_read_write_data(self.websocket_lambda)
        connections_table.grant_read_write_data(self.rest_lambda)
        connections_table.grant_read_write_data(self.websocket_lambda)

        # --- REST API Gateway (proxy integration) ---
        self.rest_api = apigw.LambdaRestApi(
            self,
            "RestApi",
            rest_api_name="live-poll-rest-api",
            handler=self.rest_lambda,
            proxy=True,
            deploy_options=apigw.StageOptions(stage_name="prod"),
        )

        # --- WebSocket API Gateway (L1 constructs) ---
        self.websocket_api = apigwv2.CfnApi(
            self,
            "WebSocketApi",
            name="live-poll-websocket-api",
            protocol_type="WEBSOCKET",
            route_selection_expression="$request.body.action",
        )

        # WebSocket Lambda integration
        ws_integration = apigwv2.CfnIntegration(
            self,
            "WebSocketIntegration",
            api_id=self.websocket_api.ref,
            integration_type="AWS_PROXY",
            integration_uri=(
                f"arn:aws:apigateway:{Stack.of(self).region}"
                f":lambda:path/2015-03-31/functions/"
                f"{self.websocket_lambda.function_arn}/invocations"
            ),
        )

        # WebSocket routes: $connect, $disconnect, $default
        for route_key in ["$connect", "$disconnect", "$default"]:
            apigwv2.CfnRoute(
                self,
                f"Route{route_key.replace('$', '').capitalize()}",
                api_id=self.websocket_api.ref,
                route_key=route_key,
                authorization_type="NONE",
                target=f"integrations/{ws_integration.ref}",
            )

        # WebSocket stage
        apigwv2.CfnStage(
            self,
            "WebSocketStage",
            api_id=self.websocket_api.ref,
            stage_name="prod",
            auto_deploy=True,
        )

        # WebSocket endpoint URL for broadcasting
        ws_endpoint_url = (
            f"https://{self.websocket_api.ref}.execute-api."
            f"{Stack.of(self).region}.amazonaws.com/prod"
        )

        # Set WS_ENDPOINT_URL on the REST Lambda for broadcasting
        self.rest_lambda.add_environment("WS_ENDPOINT_URL", ws_endpoint_url)

        # --- Grant API Gateway invoke permission to WebSocket Lambda ---
        self.websocket_lambda.add_permission(
            "ApiGwInvokeWebSocket",
            principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
            source_arn=(
                f"arn:aws:execute-api:{Stack.of(self).region}:"
                f"{Stack.of(self).account}:{self.websocket_api.ref}/*"
            ),
        )

        # --- Grant API Gateway Management API permissions to REST Lambda ---
        self.rest_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["execute-api:ManageConnections"],
                resources=[
                    f"arn:aws:execute-api:{Stack.of(self).region}:"
                    f"{Stack.of(self).account}:{self.websocket_api.ref}/prod/POST/@connections/*"
                ],
            )
        )

        # --- CDK Outputs ---

        # Store REST API URL in SSM for other stacks to reference
        _ssm.StringParameter(
            self,
            "LambdaUrlParam",
            parameter_name="/live-poll/lambda-url",
            string_value=self.rest_api.url,
        )

        # Store WebSocket URL in SSM
        _ssm.StringParameter(
            self,
            "LambdaWsUrlParam",
            parameter_name="/live-poll/lambda-ws-url",
            string_value=(
                f"wss://{self.websocket_api.ref}.execute-api."
                f"{Stack.of(self).region}.amazonaws.com/prod"
            ),
        )

        CfnOutput(
            self,
            "RestApiUrl",
            value=self.rest_api.url,
            description="REST API Gateway HTTPS URL",
        )

        CfnOutput(
            self,
            "WebSocketApiUrl",
            value=(
                f"wss://{self.websocket_api.ref}.execute-api."
                f"{Stack.of(self).region}.amazonaws.com/prod"
            ),
            description="WebSocket API Gateway URL",
        )
