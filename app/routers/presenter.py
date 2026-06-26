"""Presenter router — authenticated endpoints for session control.

Provides the presenter with access to all polls (visible and hidden)
after validating the secret key query parameter.
"""

import hmac

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.models.poll import Poll
from app.services import poll_service

router = APIRouter(prefix="/presenter")


@router.get("/polls", response_model=list[Poll])
def get_all_polls(key: str = Query(..., description="Presenter secret key")) -> list[Poll]:
    """Return all polls (visible and hidden) for the presenter view.

    Validates the provided key against the configured PRESENTER_SECRET_KEY
    using constant-time comparison to prevent timing attacks.
    Returns 403 if the key is missing or does not match.
    """
    if not settings.PRESENTER_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Access denied")
    if not hmac.compare_digest(key, settings.PRESENTER_SECRET_KEY):
        raise HTTPException(status_code=403, detail="Access denied")

    return poll_service.get_all_polls()
