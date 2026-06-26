"""Application configuration loaded from environment variables.

Provides sensible defaults for local development. In production (EC2, ECS, Lambda),
these are set via CDK stack environment variables.
"""

import os


class Settings:
    """Application settings read from environment variables."""

    def __init__(self) -> None:
        self.DYNAMODB_TABLE: str = os.environ.get("DYNAMODB_TABLE", "live-poll-app")
        self.CONNECTIONS_TABLE: str = os.environ.get("CONNECTIONS_TABLE", "live-poll-connections")
        self.WS_ENDPOINT_URL: str = os.environ.get("WS_ENDPOINT_URL", "")
        self.AWS_REGION: str = os.environ.get("AWS_REGION", "eu-west-2")

        # Presenter secret key — required in production, optional for local dev/health checks
        self.PRESENTER_SECRET_KEY: str = os.environ.get("PRESENTER_SECRET_KEY", "")
        if not self.PRESENTER_SECRET_KEY:
            import warnings

            warnings.warn(
                "PRESENTER_SECRET_KEY environment variable is not set. "
                "Presenter endpoints will reject all requests. "
                "See cdk/cdk_config.example.py for details.",
                stacklevel=2,
            )


# Singleton instance used throughout the application
settings = Settings()
