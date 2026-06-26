# Feature: live-poll-app, Property 9: Stale Lambda connection cleanup does not break broadcasts
"""Property-based test verifying that _broadcast_lambda correctly handles stale
connections: posts to all N connections, deletes M stale ones that return 410,
and successfully delivers to the remaining N-M valid connections.

**Validates: Requirements 9.5**
"""

import asyncio
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from hypothesis import given, settings
from hypothesis import strategies as st


@given(
    n=st.integers(min_value=1, max_value=20),
    data=st.data(),
)
@settings(max_examples=100)
def test_stale_lambda_connection_cleanup_does_not_break_broadcasts(
    n: int, data: st.DataObject
) -> None:
    """For any N (1-20) total connections where M (0 to N) are stale,
    calling _broadcast_lambda must:
    - Attempt post_to_connection for all N connections
    - Delete exactly M stale connections from the table
    - Successfully deliver to N-M valid connections
    """
    m = data.draw(st.integers(min_value=0, max_value=n))

    # Generate N unique connection IDs
    connection_ids = [f"conn-{i}" for i in range(n)]
    stale_ids = set(connection_ids[:m])
    valid_ids = set(connection_ids[m:])

    # Build the items returned by DynamoDB scan
    scan_items = [{"connection_id": cid} for cid in connection_ids]

    # Track which connections get deleted
    deleted_connections: list[str] = []

    # Mock DynamoDB table
    mock_table = MagicMock()
    mock_table.scan.return_value = {"Items": scan_items}
    mock_table.delete_item.side_effect = lambda Key: deleted_connections.append(
        Key["connection_id"]
    )

    # Mock DynamoDB resource
    mock_dynamodb = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    # Track successful posts
    successful_posts: list[str] = []

    def mock_post_to_connection(ConnectionId, Data):
        if ConnectionId in stale_ids:
            # Simulate 410 GoneException for stale connections
            error_response = {
                "Error": {"Code": "GoneException", "Message": "Gone"},
                "ResponseMetadata": {"HTTPStatusCode": 410},
            }
            raise ClientError(error_response, "PostToConnection")
        else:
            successful_posts.append(ConnectionId)

    # Mock API Gateway Management API client
    mock_apigw_client = MagicMock()
    mock_apigw_client.post_to_connection.side_effect = mock_post_to_connection

    # Mock boto3.client and boto3.resource
    def mock_boto3_client(service, **kwargs):
        if service == "apigatewaymanagementapi":
            return mock_apigw_client
        return MagicMock()

    def mock_boto3_resource(service, **kwargs):
        if service == "dynamodb":
            return mock_dynamodb
        return MagicMock()

    message = '{"event": "vote_update", "poll": {"poll_id": "test"}}'

    with (
        patch("app.services.broadcast.settings") as mock_settings,
        patch("boto3.client", side_effect=mock_boto3_client),
        patch("boto3.resource", side_effect=mock_boto3_resource),
    ):
        mock_settings.WS_ENDPOINT_URL = "https://execute-api.eu-west-2.amazonaws.com/prod"
        mock_settings.AWS_REGION = "eu-west-2"
        mock_settings.CONNECTIONS_TABLE = "live-poll-connections"

        from app.services.broadcast import _broadcast_lambda

        asyncio.run(_broadcast_lambda(message))

    # Assert: all N connections were attempted
    assert mock_apigw_client.post_to_connection.call_count == n

    # Assert: M stale connections were deleted from the table
    assert len(deleted_connections) == m
    assert set(deleted_connections) == stale_ids

    # Assert: N-M valid connections received the message successfully
    assert len(successful_posts) == n - m
    assert set(successful_posts) == valid_ids
