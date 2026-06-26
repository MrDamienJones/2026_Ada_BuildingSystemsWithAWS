"""Poll service — business logic layer for the Live Poll App.

Wraps the DynamoDB data access layer (app.db.dynamo) and adds validation
before delegating persistence operations.
"""

from app.db.dynamo import (
    get_all_polls as _db_get_all_polls,
)
from app.db.dynamo import (
    get_poll_by_id as _db_get_poll_by_id,
)
from app.db.dynamo import (
    get_poll_results as _db_get_poll_results,
)
from app.db.dynamo import (
    get_visible_polls as _db_get_visible_polls,
)
from app.db.dynamo import (
    record_vote as _db_record_vote,
)
from app.db.dynamo import (
    update_poll_visibility as _db_update_poll_visibility,
)
from app.models.poll import Poll


def get_visible_polls() -> list[Poll]:
    """Return all polls that are currently visible to participants."""
    return _db_get_visible_polls()


def get_all_polls() -> list[Poll]:
    """Return all polls (visible and hidden) for the presenter view."""
    return _db_get_all_polls()


def record_vote(poll_id: str, option_id: str) -> Poll:
    """Record a vote and return the updated poll with current results.

    Delegates validation (poll exists, option belongs to poll) to the data
    access layer which raises PollNotFoundError or OptionNotFoundError.

    Args:
        poll_id: The poll to vote on.
        option_id: The option within that poll to vote for.

    Returns:
        The updated Poll model with current aggregated vote counts.

    Raises:
        PollNotFoundError: If poll_id does not exist.
        OptionNotFoundError: If option_id does not belong to the poll.
        DynamoDBWriteError: If the write operation fails.
    """
    _db_record_vote(poll_id, option_id)
    return _db_get_poll_results(poll_id)


def toggle_visibility(poll_id: str, visibility: str) -> Poll:
    """Update a poll's visibility state.

    Validates the visibility value is exactly "visible" or "hidden",
    converts it to a boolean, and persists to DynamoDB.

    Args:
        poll_id: The poll whose visibility should change.
        visibility: Must be "visible" or "hidden".

    Returns:
        The updated Poll model reflecting the new visibility state.

    Raises:
        ValueError: If visibility is not "visible" or "hidden".
        PollNotFoundError: If poll_id does not exist.
        DynamoDBWriteError: If the write operation fails.
    """
    if visibility not in ("visible", "hidden"):
        raise ValueError("visibility must be 'visible' or 'hidden'")

    visible_bool = visibility == "visible"
    _db_update_poll_visibility(poll_id, visible_bool)
    return _db_get_poll_by_id(poll_id)
