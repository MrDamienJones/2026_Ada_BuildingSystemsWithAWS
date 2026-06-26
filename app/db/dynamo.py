"""DynamoDB data access layer for the Live Poll App.

Uses a single-table design with composite keys:
  PK = POLL#{poll_id}
  SK = META | OPTION#{option_id} | VOTE#{vote_id}

Provides helpers for reading polls, recording votes, and updating visibility.
"""

import uuid
from datetime import UTC, datetime

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.config import settings
from app.models.poll import Option, Poll

# --- Custom Exceptions ---


class PollNotFoundError(Exception):
    """Raised when a poll_id does not exist in DynamoDB."""

    def __init__(self, poll_id: str) -> None:
        self.poll_id = poll_id
        super().__init__(f"Poll not found: {poll_id}")


class OptionNotFoundError(Exception):
    """Raised when an option_id does not belong to the specified poll."""

    def __init__(self, poll_id: str, option_id: str) -> None:
        self.poll_id = poll_id
        self.option_id = option_id
        super().__init__(f"Option '{option_id}' not found on poll '{poll_id}'")


class DynamoDBWriteError(Exception):
    """Raised when a DynamoDB write operation fails."""

    def __init__(self, message: str = "DynamoDB write operation failed") -> None:
        super().__init__(message)


# --- DynamoDB Client ---


def _get_table():
    """Return a boto3 DynamoDB Table resource for the main table."""
    dynamodb = boto3.resource("dynamodb", region_name=settings.AWS_REGION)
    return dynamodb.Table(settings.DYNAMODB_TABLE)


# --- Internal Helpers ---


def _build_poll_from_items(items: list[dict]) -> Poll | None:
    """Aggregate DynamoDB items for a single poll into a Poll model.

    Expects items sharing the same PK (POLL#{poll_id}), containing one META item,
    zero or more OPTION items, and zero or more VOTE items.

    Returns None if no META item is found.
    """
    meta = None
    options: dict[str, Option] = {}
    vote_counts: dict[str, int] = {}

    for item in items:
        sk = item.get("SK", "")

        if sk == "META":
            meta = item
        elif sk.startswith("OPTION#"):
            option_id = sk.split("#", 1)[1]
            label = item.get("label", "")
            options[option_id] = Option(
                option_id=option_id,
                label=label,
                vote_count=0,
            )
        elif sk.startswith("VOTE#"):
            option_id = item.get("option_id", "")
            if option_id:
                vote_counts[option_id] = vote_counts.get(option_id, 0) + 1

    if meta is None:
        return None

    # Apply vote counts to options (only count votes for existing options)
    for option_id, count in vote_counts.items():
        if option_id in options:
            options[option_id].vote_count = count

    poll_id = meta.get("PK", "").split("#", 1)[-1]
    # Total votes = sum of votes for existing options only (orphaned votes excluded)
    total_votes = sum(opt.vote_count for opt in options.values())
    question = meta.get("question", "")

    # Sort options by order attribute if present
    sorted_options = sorted(
        options.values(),
        key=lambda o: next(
            (item.get("order", 0) for item in items if item.get("SK") == f"OPTION#{o.option_id}"),
            0,
        ),
    )

    return Poll(
        poll_id=poll_id,
        question=question,
        visible=meta.get("visible", False),
        options=sorted_options,
        total_votes=total_votes,
    )


def _query_all_polls() -> list[Poll]:
    """Query all polls from DynamoDB by scanning and grouping by PK."""
    table = _get_table()

    try:
        response = table.scan()
        all_items = response.get("Items", [])

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            all_items.extend(response.get("Items", []))
    except ClientError as e:
        raise DynamoDBWriteError(f"DynamoDB read error: {e}") from e

    # Group items by PK
    polls_by_pk: dict[str, list[dict]] = {}
    for item in all_items:
        pk = item.get("PK", "")
        if not pk:
            continue
        if pk not in polls_by_pk:
            polls_by_pk[pk] = []
        polls_by_pk[pk].append(item)

    # Build Poll models
    polls: list[Poll] = []
    for pk_items in polls_by_pk.values():
        poll = _build_poll_from_items(pk_items)
        if poll is not None:
            polls.append(poll)

    return polls


# --- Public API ---


def get_visible_polls() -> list[Poll]:
    """Return all polls where visible=True, with aggregated option vote counts."""
    all_polls = _query_all_polls()
    return [p for p in all_polls if p.visible]


def get_all_polls() -> list[Poll]:
    """Return all polls (visible and hidden), with aggregated option vote counts."""
    return _query_all_polls()


def get_poll_by_id(poll_id: str) -> Poll:
    """Return a single poll by ID with aggregated vote counts.

    Raises:
        PollNotFoundError: If no poll with the given ID exists.
    """
    table = _get_table()

    try:
        response = table.query(KeyConditionExpression=Key("PK").eq(f"POLL#{poll_id}"))
    except ClientError as e:
        raise DynamoDBWriteError(f"DynamoDB read error: {e}") from e

    items = response.get("Items", [])
    if not items:
        raise PollNotFoundError(poll_id)

    poll = _build_poll_from_items(items)
    if poll is None:
        raise PollNotFoundError(poll_id)

    return poll


def record_vote(poll_id: str, option_id: str) -> None:
    """Record a vote for the given option on the given poll.

    Generates a unique vote_id (uuid4) and writes the vote item to DynamoDB.

    Raises:
        PollNotFoundError: If the poll does not exist.
        OptionNotFoundError: If the option does not belong to the poll.
        DynamoDBWriteError: If the write operation fails.
    """
    table = _get_table()

    # Verify poll exists and option belongs to it
    try:
        response = table.query(
            KeyConditionExpression=Key("PK").eq(f"POLL#{poll_id}") & Key("SK").eq("META"),
        )
    except ClientError as e:
        raise DynamoDBWriteError(f"DynamoDB read error: {e}") from e

    meta_items = response.get("Items", [])
    if not meta_items:
        raise PollNotFoundError(poll_id)

    # Check the option exists
    try:
        option_response = table.get_item(Key={"PK": f"POLL#{poll_id}", "SK": f"OPTION#{option_id}"})
    except ClientError as e:
        raise DynamoDBWriteError(f"DynamoDB read error: {e}") from e

    if "Item" not in option_response:
        raise OptionNotFoundError(poll_id, option_id)

    # Write the vote record
    vote_id = str(uuid.uuid4())
    voted_at = datetime.now(UTC).isoformat()

    try:
        table.put_item(
            Item={
                "PK": f"POLL#{poll_id}",
                "SK": f"VOTE#{vote_id}",
                "option_id": option_id,
                "voted_at": voted_at,
            }
        )
    except ClientError as e:
        raise DynamoDBWriteError(f"Failed to record vote: {e}") from e


def update_poll_visibility(poll_id: str, visible: bool) -> None:
    """Update the visibility attribute on a poll's META item.

    Raises:
        PollNotFoundError: If the poll does not exist.
        DynamoDBWriteError: If the write operation fails.
    """
    table = _get_table()

    # Verify the poll exists first
    try:
        response = table.get_item(Key={"PK": f"POLL#{poll_id}", "SK": "META"})
    except ClientError as e:
        raise DynamoDBWriteError(f"DynamoDB read error: {e}") from e

    if "Item" not in response:
        raise PollNotFoundError(poll_id)

    # Update the visible attribute
    try:
        table.update_item(
            Key={"PK": f"POLL#{poll_id}", "SK": "META"},
            UpdateExpression="SET visible = :v",
            ExpressionAttributeValues={":v": visible},
        )
    except ClientError as e:
        raise DynamoDBWriteError(f"Failed to update visibility: {e}") from e


def get_poll_results(poll_id: str) -> Poll:
    """Return the poll with current aggregated vote counts.

    This is equivalent to get_poll_by_id — included as a semantic alias
    for clarity when callers want the latest results after a vote.

    Raises:
        PollNotFoundError: If the poll does not exist.
    """
    return get_poll_by_id(poll_id)
