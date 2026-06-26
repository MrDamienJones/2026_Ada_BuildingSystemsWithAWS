"""Polls router — participant-facing REST endpoints.

Provides:
  GET  /polls                       → visible polls with vote counts
  POST /polls/{poll_id}/votes       → record a vote
  PATCH /polls/{poll_id}/visibility → update poll visibility (presenter action, authenticated)
"""

import hmac

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.db.dynamo import DynamoDBWriteError, OptionNotFoundError, PollNotFoundError
from app.models.poll import Poll, VisibilityUpdate, VoteRequest, VoteResponse
from app.services import poll_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Broadcast placeholder — will delegate to app.services.broadcast (task 3.5)
# ---------------------------------------------------------------------------


async def _broadcast_update(event: str, poll: Poll) -> None:
    """Broadcast an update to all connected clients via the broadcast service."""
    from app.services.broadcast import broadcast_poll_update

    await broadcast_poll_update(event, poll)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/polls", response_model=list[Poll])
async def get_polls() -> list[Poll]:
    """Return all visible polls with aggregated vote counts."""
    try:
        return poll_service.get_visible_polls()
    except DynamoDBWriteError:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from None


@router.post("/polls/{poll_id}/votes", response_model=VoteResponse)
async def cast_vote(poll_id: str, body: VoteRequest) -> VoteResponse:
    """Record a vote for the specified option on the given poll."""
    try:
        updated_poll = poll_service.record_vote(poll_id, body.option_id)
    except PollNotFoundError:
        raise HTTPException(status_code=404, detail="Poll not found") from None
    except OptionNotFoundError:
        raise HTTPException(status_code=404, detail="Option not found") from None
    except DynamoDBWriteError:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from None

    await _broadcast_update("vote_update", updated_poll)

    return VoteResponse(poll_id=poll_id, option_id=body.option_id, success=True)


@router.patch("/polls/{poll_id}/visibility", response_model=Poll)
async def update_visibility(
    poll_id: str,
    body: VisibilityUpdate,
    key: str = Query(..., description="Presenter secret key"),
) -> Poll:
    """Update a poll's visibility state (visible or hidden).

    Requires presenter authentication via the secret key query parameter.
    """
    if not settings.PRESENTER_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Access denied")
    if not hmac.compare_digest(key, settings.PRESENTER_SECRET_KEY):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        updated_poll = poll_service.toggle_visibility(poll_id, body.visibility)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except PollNotFoundError:
        raise HTTPException(status_code=404, detail="Poll not found") from None
    except DynamoDBWriteError:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from None

    await _broadcast_update("visibility_change", updated_poll)

    return updated_poll
