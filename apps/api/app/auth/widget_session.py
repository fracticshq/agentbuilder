"""
Widget session tokens.

The public widget chat endpoints are unauthenticated by design (they run on
third-party websites with no login). To stop conversation hijacking, the server
issues a signed, opaque session token that binds a freshly-minted
``conversation_id`` and ``user_id`` to a single ``agent_id``. Subsequent message
calls must present this token; the server derives the conversation and user
identity *from the token*, ignoring any client-supplied values. A caller can
therefore only ever read or write the conversation their token was minted for.

Tokens are signed with the application ``SECRET_KEY`` (HS256), the same key used
for dashboard JWTs, so no new secret material is required.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
import structlog

from ..config import Settings

logger = structlog.get_logger(__name__)
settings = Settings()

WIDGET_SESSION_TOKEN_TYPE = "widget_session"
# Conversations are long-lived; tokens can be refreshed via the session endpoint
# by presenting a still-valid token, which preserves user/conversation identity.
WIDGET_SESSION_TTL = timedelta(days=7)


@dataclass(frozen=True)
class WidgetSession:
    conversation_id: str
    user_id: str
    agent_id: str


def issue_widget_session(agent_id: str) -> tuple[str, WidgetSession]:
    """Mint a fresh widget session with server-generated conversation and user ids."""
    session = WidgetSession(
        conversation_id=f"conv_{uuid.uuid4().hex}",
        user_id=f"user_{uuid.uuid4().hex}",
        agent_id=agent_id,
    )
    return _encode(session), session


def encode_widget_session(session: WidgetSession) -> str:
    """Re-sign an existing session (used to refresh expiry on resume)."""
    return _encode(session)


def _encode(session: WidgetSession) -> str:
    now = datetime.utcnow()
    payload = {
        "cid": session.conversation_id,
        "uid": session.user_id,
        "aid": session.agent_id,
        "type": WIDGET_SESSION_TOKEN_TYPE,
        "iat": now,
        "exp": now + WIDGET_SESSION_TTL,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_widget_session(token: Optional[str], expected_agent_id: Optional[str] = None) -> Optional[WidgetSession]:
    """
    Validate a widget session token and return its bound identity.

    Returns ``None`` if the token is missing, malformed, expired, the wrong type,
    or bound to a different agent than the one being addressed.
    """
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except JWTError as exc:
        logger.info("widget_session_decode_failed", error=str(exc))
        return None

    if payload.get("type") != WIDGET_SESSION_TOKEN_TYPE:
        return None

    conversation_id = payload.get("cid")
    user_id = payload.get("uid")
    agent_id = payload.get("aid")
    if not conversation_id or not user_id or not agent_id:
        return None

    if expected_agent_id is not None and agent_id != expected_agent_id:
        logger.warning(
            "widget_session_agent_mismatch",
            token_agent_id=agent_id,
            expected_agent_id=expected_agent_id,
        )
        return None

    return WidgetSession(conversation_id=conversation_id, user_id=user_id, agent_id=agent_id)
