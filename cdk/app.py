#!/usr/bin/env python3
"""CDK app entry point for the Live Poll App infrastructure."""

import aws_cdk as cdk
from cdk_config import AWS_ACCOUNT_ID, AWS_REGION
from ec2_stack import EC2Stack
from ecs_stack import ECSStack
from frontend_stack import FrontendStack
from lambda_stack import LambdaStack
from shared_stack import SharedStack

app = cdk.App()
env = cdk.Environment(account=AWS_ACCOUNT_ID, region=AWS_REGION)

shared = SharedStack(app, "SharedStack", env=env)

# Compute stacks (must be deployed before FrontendStack reads their SSM params)
ec2 = EC2Stack(app, "EC2Stack", env=env, shared_stack=shared)
ecs = ECSStack(app, "ECSStack", env=env, shared_stack=shared)
lambda_stack = LambdaStack(app, "LambdaStack", env=env, shared_stack=shared)

# Frontend hosting stack (S3 + CloudFront)
# Reads SSM params at synth time — deploy compute stacks first on initial setup
frontend = FrontendStack(app, "FrontendStack", env=env)
frontend.add_dependency(ec2)
frontend.add_dependency(ecs)
frontend.add_dependency(lambda_stack)

app.synth()
