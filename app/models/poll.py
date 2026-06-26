"""Pydantic data models for the Live Poll App.

Defines the core data structures used across the backend API for polls,
votes, visibility control, and real-time broadcast messages.
"""

from typing import Literal

from pydantic import BaseModel


class Option(BaseModel):
    """A single answer option within a poll."""

    option_id: str
    label: str
    vote_count: int = 0


class Poll(BaseModel):
    """A poll with its question, options, and vote tally."""

    poll_id: str
    question: str
    visible: bool
    options: list[Option]
    total_votes: int = 0


class VoteRequest(BaseModel):
    """Payload for submitting a vote on a poll option."""

    option_id: str


class VoteResponse(BaseModel):
    """Response returned after a vote is recorded."""

    poll_id: str
    option_id: str
    success: bool


class VisibilityUpdate(BaseModel):
    """Payload for updating a poll's visibility state.

    The visibility field is restricted to exactly "visible" or "hidden".
    Any other value will be rejected by Pydantic validation.
    """

    visibility: Literal["visible", "hidden"]


class BroadcastMessage(BaseModel):
    """Message broadcast to all connected clients via WebSocket.

    Sent when a vote is recorded or a poll's visibility changes.
    """

    event: Literal["vote_update", "visibility_change"]
    poll: Poll
