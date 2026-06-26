"""CDK deployment configuration — EXAMPLE TEMPLATE.

Copy this file to cdk_config.py and fill in your values.
cdk_config.py is gitignored and will not be committed.
"""

# AWS Account & Region
AWS_ACCOUNT_ID = "123456789012"
AWS_REGION = "eu-west-2"

# Application secrets
PRESENTER_SECRET_KEY = "change-me-to-a-real-secret"  # noqa: S105  # pragma: allowlist secret
