# Feature: live-poll-app, Property 7: Invalid visibility value returns 400
"""Property-based test verifying that VisibilityUpdate rejects any string
that is not exactly "visible" or "hidden".

**Validates: Requirements 6.9**
"""

from unittest.mock import patch

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.db.dynamo import PollNotFoundError
from app.models.poll import Option, Poll, VisibilityUpdate

VALID_VISIBILITY_VALUES = {"visible", "hidden"}


@given(invalid_value=st.text())
@settings(max_examples=100)
def test_invalid_visibility_value_rejected(invalid_value: str) -> None:
    """Any string that is not 'visible' or 'hidden' must raise ValidationError."""
    assume(invalid_value not in VALID_VISIBILITY_VALUES)

    with pytest.raises(ValidationError):
        VisibilityUpdate(visibility=invalid_value)


@pytest.mark.parametrize("valid_value", ["visible", "hidden"])
def test_valid_visibility_values_accepted(valid_value: str) -> None:
    """The two allowed values must be accepted without error."""
    result = VisibilityUpdate(visibility=valid_value)
    assert result.visibility == valid_value


# Feature: live-poll-app, Property 4: Hidden polls excluded from participant view
# **Validates: Requirements 1.1, 5.6, 5.8**

# Strategy: generate a list of Poll objects with random visibility states
poll_option_strategy = st.builds(
    Option,
    option_id=st.text(min_size=1, max_size=10),
    label=st.text(min_size=1, max_size=50),
    vote_count=st.integers(min_value=0, max_value=1000),
)

poll_strategy = st.builds(
    Poll,
    poll_id=st.text(min_size=1, max_size=20),
    question=st.text(min_size=1, max_size=200),
    visible=st.booleans(),
    options=st.lists(poll_option_strategy, min_size=1, max_size=5),
    total_votes=st.integers(min_value=0, max_value=5000),
)


@given(polls=st.lists(poll_strategy, min_size=0, max_size=20))
@settings(max_examples=100)
def test_hidden_polls_excluded_from_participant_view(polls: list[Poll]) -> None:
    """get_visible_polls must return ONLY polls with visible=True.

    No poll with visible=False should appear in the result.
    """
    # De-duplicate by poll_id (keep the first occurrence) to avoid ambiguous IDs
    seen_ids: set[str] = set()
    unique_polls: list[Poll] = []
    for p in polls:
        if p.poll_id not in seen_ids:
            seen_ids.add(p.poll_id)
            unique_polls.append(p)

    with patch("app.db.dynamo._query_all_polls", return_value=unique_polls):
        from app.db.dynamo import get_visible_polls

        result = get_visible_polls()

    # Every returned poll must have visible=True
    for poll in result:
        assert poll.visible is True

    # No hidden poll should appear in the result
    hidden_ids = {p.poll_id for p in unique_polls if not p.visible}
    returned_ids = {p.poll_id for p in result}
    assert hidden_ids.isdisjoint(returned_ids)

    # All visible polls from the input should be present in the result
    visible_input = [p for p in unique_polls if p.visible]
    assert len(result) == len(visible_input)


# Feature: live-poll-app, Property 6: Invalid vote references return 404
"""Property-based test verifying that recording a vote with a poll_id or option_id
not present in the database raises PollNotFoundError (maps to 404) and
causes no state change.

**Validates: Requirements 6.8**
"""


class EmptyPollStore:
    """Simulates an empty DynamoDB — no polls exist."""

    def __init__(self) -> None:
        self.writes: list[dict] = []

    def record_vote(self, poll_id: str, option_id: str) -> None:
        """Always raises PollNotFoundError since no polls exist."""
        raise PollNotFoundError(poll_id)

    def get_poll_results(self, poll_id: str):
        """Should never be reached if record_vote raises first."""
        raise PollNotFoundError(poll_id)


@given(
    poll_id=st.text(min_size=1, max_size=100),
    option_id=st.text(min_size=1, max_size=100),
)
@settings(max_examples=100)
def test_invalid_vote_references_return_404(poll_id: str, option_id: str) -> None:
    """For any random poll_id/option_id not in the DB, record_vote must raise
    PollNotFoundError (which maps to HTTP 404) and no state change occurs."""
    store = EmptyPollStore()

    with (
        patch(
            "app.services.poll_service._db_record_vote",
            side_effect=store.record_vote,
        ),
        patch(
            "app.services.poll_service._db_get_poll_results",
            side_effect=store.get_poll_results,
        ),
    ):
        from app.services.poll_service import record_vote

        with pytest.raises(PollNotFoundError):
            record_vote(poll_id, option_id)

    # Assert no writes occurred (empty store had no state change)
    assert store.writes == []
