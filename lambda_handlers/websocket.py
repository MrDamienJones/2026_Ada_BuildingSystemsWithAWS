"""Lambda handler for API Gateway WebSocket lifecycle events.

Handles $connect, $disconnect, and $default route keys for the
Lambda_Stack WebSocket API. Connection IDs are stored in a DynamoDB
connections table with a TTL for automatic stale-entry cleanup.
"""

import os
import time
from datetime import UTC, datetime

import boto3

CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE", "live-poll-connections")
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-2")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
connections_table = dynamodb.Table(CONNECTIONS_TABLE)

# TTL: 24 hours from connection time
TTL_SECONDS = 24 * 60 * 60


def handler(event, context):
    """Route WebSocket lifecycle events to the appropriate action.

    Args:
        event: API Gateway WebSocket event containing requestContext
               with routeKey and connectionId.
        context: Lambda context (unused).

    Returns:
        dict with statusCode and body.
    """
    try:
        route_key = event["requestContext"]["routeKey"]
        connection_id = event["requestContext"]["connectionId"]
    except (KeyError, TypeError):
        return {"statusCode": 400, "body": "Invalid event structure"}

    if route_key == "$connect":
        return _on_connect(connection_id)
    elif route_key == "$disconnect":
        return _on_disconnect(connection_id)
    elif route_key == "$default":
        # Server-push only — no client messages expected
        return {"statusCode": 200, "body": "OK"}
    else:
        return {"statusCode": 400, "body": "Unknown route"}


def _on_connect(connection_id: str) -> dict:
    """Store connection ID in DynamoDB with a TTL."""
    now = int(time.time())
    try:
        connections_table.put_item(
            Item={
                "connection_id": connection_id,
                "connected_at": datetime.now(UTC).isoformat(),
                "ttl": now + TTL_SECONDS,
            }
        )
    except Exception as e:
        print(f"ERROR: Failed to store connection {connection_id}: {e}")
        return {"statusCode": 500, "body": "Failed to connect"}
    return {"statusCode": 200, "body": "Connected"}


def _on_disconnect(connection_id: str) -> dict:
    """Remove connection ID from DynamoDB."""
    try:
        connections_table.delete_item(Key={"connection_id": connection_id})
    except Exception as e:
        print(f"ERROR: Failed to delete connection {connection_id}: {e}")
        # Return 200 anyway — connection is already gone from the client's perspective
    return {"statusCode": 200, "body": "Disconnected"}
