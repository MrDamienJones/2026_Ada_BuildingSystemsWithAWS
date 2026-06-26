"""Unit tests for presenter authentication via secret key query parameter.

**Validates: Requirements 5.1**

Tests that the presenter endpoint correctly validates the secret key,
returning 200 for valid keys and 403 for invalid/wrong keys.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models.poll import Option, Poll

client = TestClient(app)

SAMPLE_POLLS = [
    Poll(
        poll_id="test-poll-1",
        question="What is your favourite language?",
        visible=True,
        options=[
            Option(option_id="python", label="Python", vote_count=5),
            Option(option_id="js", label="JavaScript", vote_count=3),
        ],
        total_votes=8,
    ),
    Poll(
        poll_id="test-poll-2",
        question="Pineapple on pizza?",
        visible=False,
        options=[
            Option(option_id="yes", label="Yes", vote_count=2),
            Option(option_id="no", label="No", vote_count=7),
        ],
        total_votes=9,
    ),
]


@patch("app.services.poll_service.get_all_polls", return_value=SAMPLE_POLLS)
@patch("app.config.settings.PRESENTER_SECRET_KEY", "local-dev-secret")
def test_valid_key_returns_200(mock_get_all: object) -> None:
    """GET /presenter/polls with the correct key returns 200 and all polls."""
    response = client.get("/presenter/polls", params={"key": "local-dev-secret"})

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["poll_id"] == "test-poll-1"
    assert data[1]["poll_id"] == "test-poll-2"


def test_missing_key_returns_422() -> None:
    """GET /presenter/polls with no key param returns 422 (FastAPI requires it)."""
    response = client.get("/presenter/polls")

    # FastAPI treats missing required query param as 422 Unprocessable Entity
    assert response.status_code == 422


@patch("app.services.poll_service.get_all_polls", return_value=SAMPLE_POLLS)
def test_wrong_key_returns_403(mock_get_all: object) -> None:
    """GET /presenter/polls with an incorrect key returns 403 Access Denied."""
    response = client.get("/presenter/polls", params={"key": "wrong-key"})

    assert response.status_code == 403
    assert "Access denied" in response.json().get("detail", "")
