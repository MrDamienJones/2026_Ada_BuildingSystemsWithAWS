"""Broadcast service for pushing real-time updates to all connected clients.

Provides a unified broadcast interface that works across deployment models:
- EC2/ECS: iterates in-memory WebSocket connections, sends JSON, removes dead connections
- Lambda: reads connection IDs from DynamoDB connections table, calls API Gateway
  Management API, deletes stale IDs on 410 (GoneException) error
"""

import logging

from app.config import settings
from app.models.poll import BroadcastMessage, Poll

logger = logging.getLogger(__name__)


async def broadcast_poll_update(event: str, poll: Poll) -> None:
    """Broadcast a poll update to all connected clients.

    Constructs a BroadcastMessage and dispatches it via the appropriate
    transport based on the deployment mode.

    Args:
        event: The event type - either "vote_update" or "visibility_change".
        poll: The updated Poll object to include in the broadcast payload.
    """
    message = BroadcastMessage(event=event, poll=poll)  # type: ignore[arg-type]
    message_json = message.model_dump_json()

    if settings.WS_ENDPOINT_URL:
        # Lambda mode: use API Gateway Management API
        await _broadcast_lambda(message_json)
    else:
        # EC2/ECS mode: push directly to in-memory WebSocket connections
        await _broadcast_websocket(message_json)


async def _broadcast_websocket(message: str) -> None:
    """Broadcast a message to all in-memory WebSocket connections (EC2/ECS).

    Iterates all active connections and sends the message. If a connection
    raises an exception (dead/disconnected), it is removed from the set.
    """
    from app.routers.websocket import active_connections

    dead_connections = set()

    for connection in active_connections.copy():
        try:
            await connection.send_text(message)
        except Exception as e:
            logger.warning("Removing dead WebSocket connection: %s", type(e).__name__)
            dead_connections.add(connection)

    # Remove dead connections from the active set
    for connection in dead_connections:
        active_connections.discard(connection)


async def _broadcast_lambda(message: str) -> None:
    """Broadcast a message via API Gateway Management API (Lambda).

    Reads all connection IDs from the DynamoDB connections table, posts the
    message to each via the API Gateway Management API, and deletes stale
    connection IDs that return a 410 GoneException.
    """
    import boto3
    from botocore.exceptions import ClientError

    # Create API Gateway Management API client
    apigw_client = boto3.client(
        "apigatewaymanagementapi",
        endpoint_url=settings.WS_ENDPOINT_URL,
        region_name=settings.AWS_REGION,
    )

    # Create DynamoDB resource to scan connections table
    dynamodb = boto3.resource("dynamodb", region_name=settings.AWS_REGION)
    connections_table = dynamodb.Table(settings.CONNECTIONS_TABLE)

    # Scan for all connection IDs
    try:
        response = connections_table.scan(ProjectionExpression="connection_id")
        connection_items = response.get("Items", [])

        # Handle pagination if there are many connections
        while "LastEvaluatedKey" in response:
            response = connections_table.scan(
                ProjectionExpression="connection_id",
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            connection_items.extend(response.get("Items", []))
    except ClientError as e:
        logger.error("Failed to scan connections table: %s", str(e))
        return

    # Post message to each connection
    for item in connection_items:
        connection_id = item.get("connection_id")
        if not connection_id:
            continue
        try:
            apigw_client.post_to_connection(
                ConnectionId=connection_id,
                Data=message.encode("utf-8"),
            )
        except ClientError as e:
            status_code = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status_code == 410:
                # Connection is stale — remove from DynamoDB
                logger.info("Deleting stale connection: %s", connection_id)
                connections_table.delete_item(Key={"connection_id": connection_id})
            else:
                logger.error("Failed to post to connection %s: %s", connection_id, str(e))
