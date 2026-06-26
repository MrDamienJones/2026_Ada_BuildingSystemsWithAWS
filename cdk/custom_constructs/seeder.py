"""CDK construct for seeding DynamoDB with poll data on deploy.

Uses a CDK custom resource backed by a Lambda function that reads
polls.json and performs conditional writes (skip if exists) to
DynamoDB. This ensures idempotent seeding across re-deploys.
"""

import os

from aws_cdk import (
    CustomResource,
    Duration,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    custom_resources as cr,
)
from constructs import Construct

SEED_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "seed_data")


class DynamoDBSeeder(Construct):
    """Custom resource that seeds DynamoDB with poll data from polls.json.

    Seeding is idempotent: existing polls are skipped via conditional puts.
    Errors surface which poll failed and halt deployment.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        table: dynamodb.ITable,
    ) -> None:
        super().__init__(scope, construct_id)

        # Read seed data at synth time to embed in Lambda environment
        polls_json_path = os.path.join(SEED_DATA_PATH, "polls.json")
        if os.path.exists(polls_json_path):
            with open(polls_json_path, encoding="utf-8") as f:
                seed_data = f.read()
        else:
            seed_data = "[]"

        # Lambda function that performs the seeding
        seeder_fn = lambda_.Function(
            self,
            "SeederFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            timeout=Duration.seconds(60),
            code=lambda_.Code.from_inline(self._get_seeder_code()),
            environment={
                "TABLE_NAME": table.table_name,
                "SEED_DATA": seed_data,
            },
        )

        # Grant DynamoDB write access
        table.grant_read_write_data(seeder_fn)

        # Custom resource provider
        provider = cr.Provider(
            self,
            "SeederProvider",
            on_event_handler=seeder_fn,
        )

        # Custom resource triggers on every deploy (uses hash of seed data)
        CustomResource(
            self,
            "SeederResource",
            service_token=provider.service_token,
            properties={
                "seed_hash": str(hash(seed_data)),
            },
        )

    @staticmethod
    def _get_seeder_code() -> str:
        """Return inline Lambda code for the seeder function."""
        return '''
import json
import os
import boto3
from botocore.exceptions import ClientError

def handler(event, context):
    """Seed DynamoDB with poll data. Idempotent via conditional puts."""
    request_type = event.get("RequestType", "Create")

    # Only seed on Create and Update, not Delete
    if request_type == "Delete":
        return {"PhysicalResourceId": "seeder"}

    table_name = os.environ["TABLE_NAME"]
    seed_data = json.loads(os.environ["SEED_DATA"])
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    for poll in seed_data:
        poll_id = poll["poll_id"]
        try:
            # Write poll metadata (skip if exists)
            table.put_item(
                Item={
                    "PK": f"POLL#{poll_id}",
                    "SK": "META",
                    "question": poll["question"],
                    "visible": False,
                    "created_at": "2024-01-01T00:00:00Z",
                },
                ConditionExpression="attribute_not_exists(PK)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                # Poll already exists, skip
                continue
            raise RuntimeError(f"Failed to seed poll '{poll_id}': {e}") from e

        # Write poll options
        for option in poll.get("options", []):
            try:
                table.put_item(
                    Item={
                        "PK": f"POLL#{poll_id}",
                        "SK": f"OPTION#{option['option_id']}",
                        "label": option["label"],
                        "order": option.get("order", 0),
                    },
                    ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
                )
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    continue
                raise RuntimeError(
                    f"Failed to seed option '{option['option_id']}' for poll '{poll_id}': {e}"
                ) from e

    return {"PhysicalResourceId": "seeder"}
'''
