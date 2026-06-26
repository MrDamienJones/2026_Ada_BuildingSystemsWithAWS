"""Unit tests for DynamoDB seeder logic — idempotency and error handling.

**Validates: Requirements 4.5, 4.6**

Tests that:
- Seeding twice produces the same records (idempotent via conditional puts)
- A non-conditional DynamoDB write failure raises RuntimeError
"""

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

# The seeder code lives inline in the CDK construct. We replicate its core
# logic here to test it in isolation. This mirrors the handler in
# cdk/custom_constructs/seeder.py::_get_seeder_code().


def seed_polls(table: object, seed_data: list[dict]) -> None:
    """Seed DynamoDB with poll data. Idempotent via conditional puts.

    This is a faithful extraction of the inline Lambda handler logic
    from the CDK seeder construct.
    """
    for poll in seed_data:
        poll_id = poll["poll_id"]
        try:
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


SAMPLE_SEED_DATA = [
    {
        "poll_id": "fav-lang",
        "question": "What is your favourite programming language?",
        "options": [
            {"option_id": "python", "label": "Python", "order": 1},
            {"option_id": "javascript", "label": "JavaScript", "order": 2},
        ],
    },
    {
        "poll_id": "pizza",
        "question": "Does pineapple belong on pizza?",
        "options": [
            {"option_id": "yes", "label": "Yes", "order": 1},
            {"option_id": "no", "label": "No", "order": 2},
        ],
    },
]


class TestSeedIdempotency:
    """Seeding twice produces the same records — second run skips existing."""

    def test_first_seed_writes_all_items(self) -> None:
        """First seed should call put_item for each poll and its options."""
        mock_table = MagicMock()

        seed_polls(mock_table, SAMPLE_SEED_DATA)

        # 2 polls (META) + 2 options each = 6 put_item calls
        assert mock_table.put_item.call_count == 6

    def test_second_seed_skips_existing(self) -> None:
        """Second seed should skip all items due to ConditionalCheckFailedException."""
        mock_table = MagicMock()

        # Simulate all items already existing
        conditional_error = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "Already exists"}},
            "PutItem",
        )
        mock_table.put_item.side_effect = conditional_error

        # Should not raise — ConditionalCheckFailedException is handled gracefully
        seed_polls(mock_table, SAMPLE_SEED_DATA)

        # put_item is called for each poll META, but since it throws immediately
        # on META, options for that poll are skipped (continue on META)
        # 2 polls = 2 put_item calls (both raise ConditionalCheckFailedException)
        assert mock_table.put_item.call_count == 2

    def test_idempotent_result_same_records(self) -> None:
        """Seeding twice yields the same number of records — no duplicates."""
        items_written: list[dict] = []

        def track_put_item(**kwargs: object) -> None:
            items_written.append(kwargs["Item"])

        # First seed: all writes succeed
        mock_table_first = MagicMock()
        mock_table_first.put_item.side_effect = track_put_item

        seed_polls(mock_table_first, SAMPLE_SEED_DATA)
        first_count = len(items_written)

        # Second seed: all writes raise ConditionalCheckFailedException
        items_written.clear()
        mock_table_second = MagicMock()
        conditional_error = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "Already exists"}},
            "PutItem",
        )
        mock_table_second.put_item.side_effect = conditional_error

        seed_polls(mock_table_second, SAMPLE_SEED_DATA)
        second_count = len(items_written)

        # First run wrote 6 items, second run wrote 0 (all skipped)
        assert first_count == 6
        assert second_count == 0


class TestSeedFailureRaisesError:
    """Non-conditional DynamoDB write failures must surface as RuntimeError."""

    def test_poll_write_failure_raises_runtime_error(self) -> None:
        """A non-conditional ClientError on poll META write raises RuntimeError."""
        mock_table = MagicMock()

        # Simulate a throttling error (not ConditionalCheckFailedException)
        throttle_error = ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "Throttled"}},
            "PutItem",
        )
        mock_table.put_item.side_effect = throttle_error

        with pytest.raises(RuntimeError, match="Failed to seed poll 'fav-lang'"):
            seed_polls(mock_table, SAMPLE_SEED_DATA)

    def test_option_write_failure_raises_runtime_error(self) -> None:
        """A non-conditional ClientError on option write raises RuntimeError."""
        mock_table = MagicMock()

        # First call (poll META) succeeds, second call (option) fails
        internal_error = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "Internal error"}},
            "PutItem",
        )
        mock_table.put_item.side_effect = [None, internal_error]

        with pytest.raises(
            RuntimeError, match="Failed to seed option 'python' for poll 'fav-lang'"
        ):
            seed_polls(mock_table, SAMPLE_SEED_DATA)
