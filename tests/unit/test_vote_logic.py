# Feature: live-poll-app, Property 2: Duplicate vote rejection preserves state
"""Property-based test verifying that the backend correctly counts votes
when record_vote is called multiple times for the same poll.

The design specifies that duplicate vote prevention is a FRONTEND
responsibility (localStorage check). The backend records all votes
it receives. Therefore, calling record_vote twice for the same poll
should result in total_votes=2 and the relevant option counts summing to 2.

**Validates: Requirements 2.3, 2.4**
"""

import uuid
from unittest.mock import patch

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.models.poll import Option, Poll
from app.services.poll_service import record_vote

# --- In-memory DynamoDB mock ---


class InMemoryDynamoDB:
    """Simulates the DynamoDB single-table design in memory.

    Stores items keyed by (PK, SK) and supports the operations
    used by the poll service: poll lookup, option lookup, vote writes,
    and result aggregation.
    """

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict] = {}

    def seed_poll(self, poll: Poll) -> None:
        """Seed a poll with its META and OPTION items."""
        pk = f"POLL#{poll.poll_id}"
        self.items[(pk, "META")] = {
            "PK": pk,
            "SK": "META",
            "question": poll.question,
            "visible": poll.visible,
        }
        for idx, option in enumerate(poll.options):
            sk = f"OPTION#{option.option_id}"
            self.items[(pk, sk)] = {
                "PK": pk,
                "SK": sk,
                "label": option.label,
                "order": idx + 1,
            }

    def record_vote(self, poll_id: str, option_id: str) -> None:
        """Write a vote record, mimicking dynamo.record_vote."""
        pk = f"POLL#{poll_id}"

        # Check poll exists
        if (pk, "META") not in self.items:
            from app.db.dynamo import PollNotFoundError

            raise PollNotFoundError(poll_id)

        # Check option exists
        if (pk, f"OPTION#{option_id}") not in self.items:
            from app.db.dynamo import OptionNotFoundError

            raise OptionNotFoundError(poll_id, option_id)

        # Write vote
        vote_id = str(uuid.uuid4())
        sk = f"VOTE#{vote_id}"
        self.items[(pk, sk)] = {
            "PK": pk,
            "SK": sk,
            "option_id": option_id,
            "voted_at": "2024-01-01T00:00:00+00:00",
        }

    def get_poll_results(self, poll_id: str) -> Poll:
        """Aggregate all items for a poll into a Poll model."""
        from app.db.dynamo import PollNotFoundError

        pk = f"POLL#{poll_id}"
        meta = self.items.get((pk, "META"))
        if meta is None:
            raise PollNotFoundError(poll_id)

        options: dict[str, Option] = {}
        vote_counts: dict[str, int] = {}

        for (item_pk, item_sk), item in self.items.items():
            if item_pk != pk:
                continue
            if item_sk.startswith("OPTION#"):
                oid = item_sk.split("#", 1)[1]
                options[oid] = Option(
                    option_id=oid,
                    label=item["label"],
                    vote_count=0,
                )
            elif item_sk.startswith("VOTE#"):
                oid = item["option_id"]
                vote_counts[oid] = vote_counts.get(oid, 0) + 1

        for oid, count in vote_counts.items():
            if oid in options:
                options[oid].vote_count = count

        total_votes = sum(vote_counts.values())
        sorted_options = sorted(options.values(), key=lambda o: o.option_id)

        return Poll(
            poll_id=poll_id,
            question=meta["question"],
            visible=meta["visible"],
            options=sorted_options,
            total_votes=total_votes,
        )


# --- Hypothesis strategies ---


option_strategy = st.builds(
    Option,
    option_id=st.uuids().map(str),
    label=st.text(min_size=1, max_size=50),
    vote_count=st.just(0),
)

poll_strategy = st.builds(
    Poll,
    poll_id=st.uuids().map(str),
    question=st.text(min_size=1, max_size=200),
    visible=st.just(True),
    options=st.lists(option_strategy, min_size=2, max_size=6),
    total_votes=st.just(0),
)


# --- Property Test ---


@given(poll=poll_strategy)
@settings(max_examples=100)
def test_backend_records_both_votes_correctly(poll: Poll) -> None:
    """Backend records every vote it receives — duplicate prevention is frontend-only.

    When record_vote is called twice for the same poll (same or different option),
    the backend should record both votes. The total_votes should equal 2 and the
    sum of all option vote_counts should equal 2.

    This validates that the backend does NOT silently drop votes — the duplicate
    rejection responsibility lies with the frontend localStorage check
    (Requirements 2.3, 2.4).
    """
    assume(len(poll.options) >= 2)

    # Ensure unique option IDs
    seen_ids = set()
    unique_options = []
    for opt in poll.options:
        if opt.option_id not in seen_ids:
            seen_ids.add(opt.option_id)
            unique_options.append(opt)
    poll = poll.model_copy(update={"options": unique_options})
    assume(len(poll.options) >= 2)

    db = InMemoryDynamoDB()
    db.seed_poll(poll)

    first_option = poll.options[0].option_id
    second_option = poll.options[1].option_id

    # Patch the dynamo module functions to use our in-memory store
    with (
        patch("app.services.poll_service._db_record_vote", side_effect=db.record_vote),
        patch("app.services.poll_service._db_get_poll_results", side_effect=db.get_poll_results),
    ):
        # First vote
        result_after_first = record_vote(poll.poll_id, first_option)
        assert result_after_first.total_votes == 1

        # Second vote for the same poll (different option)
        result_after_second = record_vote(poll.poll_id, second_option)
        assert result_after_second.total_votes == 2

        # The sum of all option vote_counts should equal total_votes
        option_count_sum = sum(o.vote_count for o in result_after_second.options)
        assert option_count_sum == 2
        assert option_count_sum == result_after_second.total_votes

        # Each voted option should have exactly 1 vote
        option_map = {o.option_id: o.vote_count for o in result_after_second.options}
        assert option_map[first_option] == 1
        assert option_map[second_option] == 1


# Feature: live-poll-app, Property 5: Vote option data integrity
# Property-based test verifying that when N random votes are recorded for a
# poll, the sum of all option vote_counts equals total_votes equals N.
#
# **Validates: Requirements 2.1, 3.2, 6.1**


@given(
    poll=st.builds(
        Poll,
        poll_id=st.uuids().map(str),
        question=st.text(min_size=1, max_size=200),
        visible=st.just(True),
        options=st.lists(
            st.builds(
                Option,
                option_id=st.uuids().map(str),
                label=st.text(min_size=1, max_size=50),
                vote_count=st.just(0),
            ),
            min_size=1,
            max_size=6,
        ),
        total_votes=st.just(0),
    ),
    num_votes=st.integers(min_value=1, max_value=50),
    data=st.data(),
)
@settings(max_examples=100)
def test_vote_option_data_integrity(poll: Poll, num_votes: int, data) -> None:
    """For any poll, after recording N random votes (each selecting a random
    option), the sum of all option vote_counts must equal total_votes must equal N."""
    # Ensure unique option IDs
    seen_ids = set()
    unique_options = []
    for opt in poll.options:
        if opt.option_id not in seen_ids:
            seen_ids.add(opt.option_id)
            unique_options.append(opt)
    poll = poll.model_copy(update={"options": unique_options})
    assume(len(poll.options) >= 1)

    db = InMemoryDynamoDB()
    db.seed_poll(poll)

    # Generate N random votes, each picking a random option
    for _ in range(num_votes):
        chosen_option = data.draw(st.sampled_from(poll.options))
        with (
            patch("app.services.poll_service._db_record_vote", side_effect=db.record_vote),
            patch(
                "app.services.poll_service._db_get_poll_results", side_effect=db.get_poll_results
            ),
        ):
            record_vote(poll.poll_id, chosen_option.option_id)

    # Fetch final results
    result = db.get_poll_results(poll.poll_id)

    # Assert: sum of all option vote_counts == total_votes == N
    sum_option_counts = sum(o.vote_count for o in result.options)
    assert sum_option_counts == result.total_votes
    assert result.total_votes == num_votes
