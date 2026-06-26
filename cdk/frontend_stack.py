"""CDK stack for hosting the Live Poll App frontend via CloudFront + S3.

Reads backend URLs from SSM Parameter Store and generates a config.js
that the frontend HTML files reference. This removes the need to manually
update URLs after deploying compute stacks.
"""

import os

import boto3
from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_cloudfront as cloudfront,
)
from aws_cdk import (
    aws_cloudfront_origins as origins,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_s3_deployment as s3deploy,
)
from constructs import Construct

# Resolve frontend directory path relative to this file (cdk/frontend_stack.py)
_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
_REGION = "eu-west-2"


def _get_ssm_param(name: str) -> str:
    """Read an SSM parameter value, returning empty string if not found."""
    try:
        client = boto3.client("ssm", region_name=_REGION)
        resp = client.get_parameter(Name=name)
        return resp["Parameter"]["Value"]
    except client.exceptions.ParameterNotFound:
        return ""
    except Exception as e:
        print(f"Warning: failed to read SSM parameter '{name}': {e}")
        return ""


class FrontendStack(Stack):
    """Deploys the static frontend SPA to S3 and serves it via CloudFront.

    - Reads backend URLs from SSM Parameter Store at synth time
    - Generates config.js with the BACKENDS map
    - S3 bucket with block public access (served through CloudFront only)
    - CloudFront distribution with S3 origin using OAC
    - BucketDeployment to upload frontend/ directory contents
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Read backend URLs from SSM (set by compute stacks)
        lambda_url = _get_ssm_param("/live-poll/lambda-url").rstrip("/")
        lambda_ws_url = _get_ssm_param("/live-poll/lambda-ws-url")
        ecs_url = _get_ssm_param("/live-poll/ecs-url").rstrip("/")
        ec2_url = _get_ssm_param("/live-poll/ec2-url").rstrip("/")

        # Generate config.js content
        config_js = self._build_config_js(
            ec2_url=ec2_url,
            ecs_url=ecs_url,
            lambda_url=lambda_url,
            lambda_ws_url=lambda_ws_url,
        )

        # Write config.js to frontend directory
        config_path = os.path.join(_FRONTEND_DIR, "config.js")
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(config_js)
        except (OSError, IOError) as e:
            raise RuntimeError(f"Failed to write frontend config.js: {e}") from e

        # S3 bucket for frontend static files
        bucket = s3.Bucket(
            self,
            "FrontendBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # CloudFront Function to strip /ec2-api or /ecs-api prefix
        strip_prefix_fn = cloudfront.Function(
            self,
            "StripPrefixFunction",
            code=cloudfront.FunctionCode.from_inline(
                "function handler(event) {"
                "  var request = event.request;"
                "  request.uri = request.uri.replace(/^\\/ec2-api/, '').replace(/^\\/ecs-api/, '');"
                "  if (request.uri === '') request.uri = '/';"
                "  return request;"
                "}"
            ),
        )

        # EC2 and ECS origins for proxying API calls (avoids mixed content)
        additional_behaviors = {}

        if ec2_url:
            ec2_origin = origins.HttpOrigin(
                ec2_url.replace("http://", ""),
                protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
            )
            additional_behaviors["/ec2-api/*"] = cloudfront.BehaviorOptions(
                origin=ec2_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=strip_prefix_fn,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    )
                ],
            )

        if ecs_url:
            ecs_origin = origins.HttpOrigin(
                ecs_url.replace("http://", ""),
                protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
            )
            additional_behaviors["/ecs-api/*"] = cloudfront.BehaviorOptions(
                origin=ecs_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=strip_prefix_fn,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    )
                ],
            )

        # CloudFront distribution with S3 OAC origin
        distribution = cloudfront.Distribution(
            self,
            "FrontendDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            additional_behaviors=additional_behaviors,
            default_root_object="index.html",
        )

        # Deploy frontend/ directory contents to S3
        s3deploy.BucketDeployment(
            self,
            "DeployFrontend",
            sources=[s3deploy.Source.asset(_FRONTEND_DIR)],
            destination_bucket=bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        # Output the CloudFront distribution URL
        CfnOutput(
            self,
            "FrontendUrl",
            value="https://" + distribution.distribution_domain_name,
            description="CloudFront distribution URL for the Live Poll App frontend",
        )

    @staticmethod
    def _build_config_js(ec2_url: str, ecs_url: str, lambda_url: str, lambda_ws_url: str) -> str:
        """Generate the config.js content with backend URLs.

        EC2 and ECS use CloudFront proxy paths (/ec2-api, /ecs-api) to
        avoid mixed-content issues when the frontend is served over HTTPS.
        """
        return f"""// Auto-generated by FrontendStack at deploy time.
// Do not edit manually — values come from SSM Parameter Store.
window.BACKENDS = {{
    ec2:    {{ url: "/ec2-api", ws: null, label: "\u26a1 EC2 (Traditional)", color: "#ea580c" }},
    ecs:    {{ url: "/ecs-api", ws: null, label: "\U0001f433 ECS (Container)", color: "#2563eb" }},
    lambda: {{ url: "{lambda_url}", ws: "{lambda_ws_url}", label: "\u03bb Lambda (Serverless)", color: "#7c3aed" }}
}};
window.WS_URL = "{lambda_ws_url}";
window.API_URL = "{lambda_url}";
"""
