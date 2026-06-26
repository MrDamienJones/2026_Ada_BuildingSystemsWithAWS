# Feature: live-poll-app, Property 3: Visibility toggle round trip
"""Property-based test verifying that toggling a poll's visibility twice
returns the poll to its original visibility state.

**Validates: Requirements 5.3, 5.8**
"""

from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.poll import Option, Poll
from app.services.poll_service import toggle_visibility

# --- In-memory DynamoDB mock store ---


class InMemoryPollStore:
    """Mock DynamoDB layer that tracks poll visibility state in a dict."""

    def __init__(self) -> None:
        self.polls: dict[str, Poll] = {}

    def seed(self, poll: Poll) -> None:
        """Add a poll to the in-memory store."""
        self.polls[poll.poll_id] = poll.model_copy(deep=True)

    def update_poll_visibility(self, poll_id: str, visible_bool: bool) -> None:
        """Update the stored poll's visibility."""
        poll = self.polls[poll_id]
        self.polls[poll_id] = poll.model_copy(update={"visible": visible_bool})

    def get_poll_by_id(self, poll_id: str) -> Poll:
        """Return the poll with current visibility from store."""
        return self.polls[poll_id]


# --- Hypothesis strategies ---

poll_strategy = st.builds(
    Poll,
    poll_id=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
        min_size=1,
        max_size=20,
    ),
    question=st.text(min_size=1, max_size=100),
    visible=st.booleans(),
    options=st.just(
        [
            Option(option_id="opt-1", label="Option A", vote_count=0),
            Option(option_id="opt-2", label="Option B", vote_count=0),
        ]
    ),
    total_votes=st.just(0),
)


# --- Property test ---


@given(poll=poll_strategy)
@settings(max_examples=100)
def test_visibility_toggle_round_trip(poll: Poll) -> None:
    """Toggling visibility twice restores the poll to its original state.

    For any poll with any initial visibility (True or False):
    1. Toggle visibility to the opposite state
    2. Toggle visibility back
    3. Assert the poll's visibility matches the original
    """
    store = InMemoryPollStore()
    store.seed(poll)

    original_visibility = poll.visible

    # Determine the toggle values
    first_toggle = "hidden" if original_visibility else "visible"
    second_toggle = "visible" if original_visibility else "hidden"

    with patch(
        "app.services.poll_service._db_update_poll_visibility",
        side_effect=store.update_poll_visibility,
    ):
        with patch(
            "app.services.poll_service._db_get_poll_by_id", side_effect=store.get_poll_by_id
        ):
            # First toggle: flip the state
            toggle_visibility(poll.poll_id, first_toggle)

            # Verify state flipped
            intermediate = store.get_poll_by_id(poll.poll_id)
            assert intermediate.visible != original_visibility

            # Second toggle: flip back
            toggle_visibility(poll.poll_id, second_toggle)

            # Assert original state is restored
            final = store.get_poll_by_id(poll.poll_id)
            assert final.visible == original_visibility
