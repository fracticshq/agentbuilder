"""
WebSocket Connection Manager — Redis pub/sub fanout + shared state.

Architecture:
  - WebSocket objects are process-local (can't be serialized across instances).
    Each API instance maintains its own dict of active connections.
  - Cross-instance message delivery uses Redis pub/sub:
      send_to_widget(conv_id, msg)  → PUBLISH conv:{conv_id}:widget  <json>
      send_to_admin(conv_id, msg)   → PUBLISH conv:{conv_id}:admin   <json>
    Every instance that has a local connection for that conv_id is subscribed
    and forwards the message to its local WebSocket.
  - Shared state (human-control flag, agent_id, takeover buffer) lives in Redis:
      HASH  conv:{conv_id}:state   → {"is_human_in_control": "0", "agent_id": "..."}
      LIST  conv:{conv_id}:buffer  → [json, json, ...]

Fallback:
  When Redis is not configured, all operations degrade gracefully to
  in-process equivalents so a single-instance deployment works without Redis.
  A configured Redis client that fails is not equivalent to an absent client:
  falling back in that case would split human-takeover state between API
  instances.
"""

import asyncio
import json
import uuid
from typing import Dict, Set, Optional

import structlog
from fastapi import WebSocket

from .connections import connection_manager

logger = structlog.get_logger(__name__)

_STATE_TTL = 86400   # 24 h — auto-expire idle conversation state
_PUB_PREFIX = "conv:"
_SUBSCRIPTION_RETRY_SECONDS = 0.05


def _state_key(conversation_id: str) -> str:
    return f"{_PUB_PREFIX}{conversation_id}:state"

def _buffer_key(conversation_id: str) -> str:
    return f"{_PUB_PREFIX}{conversation_id}:buffer"

def _channel(conversation_id: str, target: str) -> str:
    return f"{_PUB_PREFIX}{conversation_id}:{target}"


class TakeoverStateUnavailableError(RuntimeError):
    """Redis-backed takeover state cannot be read or written safely."""


class TakeoverBufferIntegrityError(TakeoverStateUnavailableError):
    """The shared takeover buffer could not be decoded as trusted turns."""


class ConnectionManager:
    def __init__(self):
        self._instance_id = str(uuid.uuid4())

        # Local (per-process) WebSocket registries
        self.widget_connections: Dict[str, Set[WebSocket]] = {}
        self.admin_connections:  Dict[str, Set[WebSocket]] = {}

        # In-process fallback state (used when Redis is unavailable)
        self._local_control:  Dict[str, bool]   = {}
        self._local_agent_ids: Dict[str, str]   = {}
        self._local_buffers:  Dict[str, list]   = {}

        # asyncio tasks running the Redis subscription loops
        self._sub_tasks: Dict[str, asyncio.Task] = {}

    # ── helpers ──────────────────────────────────────────────────────────────

    def _redis(self):
        return connection_manager.redis_client

    async def _publish(self, channel: str, message: dict) -> bool:
        """Publish to Redis. Returns True on success, False if Redis is unavailable."""
        r = self._redis()
        if r is None:
            return False
        try:
            await r.publish(channel, json.dumps({
                "origin": self._instance_id,
                "message": message,
            }))
            return True
        except Exception as exc:
            logger.warning(
                "redis_publish_failed",
                channel=channel,
                error_type=type(exc).__name__,
            )
            return False

    async def _send_local(
        self,
        connections: Dict[str, Set[WebSocket]],
        conversation_id: str,
        message: dict,
    ):
        """Deliver message to all local WebSocket connections for a conversation."""
        websockets = list(connections.get(conversation_id, set()))
        failed_sockets: Set[WebSocket] = set()
        for ws in websockets:
            try:
                await ws.send_json(message)
            except Exception as exc:
                failed_sockets.add(ws)
                logger.info(
                    "ws_send_failed",
                    conversation_id=conversation_id,
                    error_type=type(exc).__name__,
                )

        if failed_sockets:
            current = connections.get(conversation_id)
            if current is not None:
                current.difference_update(failed_sockets)
                if not current:
                    connections.pop(conversation_id, None)
                    target = "widget" if connections is self.widget_connections else "admin"
                    self._stop_sub(conversation_id, target)

    def _has_local_recipients(self, conversation_id: str, target: str) -> bool:
        registry = self.widget_connections if target == "widget" else self.admin_connections
        return bool(registry.get(conversation_id))

    async def _subscribe_loop(self, conversation_id: str, target: str):
        """
        Background task: subscribe to a Redis pub/sub channel and forward
        arriving messages to local WebSocket connections.
        Runs until the task is cancelled (on disconnect).
        """
        channel = _channel(conversation_id, target)
        while self._has_local_recipients(conversation_id, target):
            r = self._redis()
            if r is None:
                return

            pubsub = None
            retry = False
            try:
                pubsub = r.pubsub()
                await pubsub.subscribe(channel)
                logger.debug("redis_subscribed", channel=channel)

                async for raw in pubsub.listen():
                    if not self._has_local_recipients(conversation_id, target):
                        return
                    if raw["type"] != "message":
                        continue
                    try:
                        data = json.loads(raw["data"])
                    except (json.JSONDecodeError, TypeError):
                        continue

                    if isinstance(data, dict) and "message" in data:
                        if data.get("origin") == self._instance_id:
                            continue
                        data = data.get("message")

                    if not isinstance(data, dict):
                        continue

                    registry = (
                        self.widget_connections if target == "widget"
                        else self.admin_connections
                    )
                    await self._send_local(registry, conversation_id, data)

                # A listener that ends without an explicit cancellation is as
                # transient as a listener exception while local recipients
                # still exist.
                retry = True
            except asyncio.CancelledError:
                return
            except Exception as exc:
                retry = True
                logger.warning(
                    "redis_subscribe_loop_error",
                    channel=channel,
                    error_type=type(exc).__name__,
                )
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.unsubscribe(channel)
                        await pubsub.aclose()
                    except Exception as exc:
                        logger.debug(
                            "redis_unsubscribe_failed",
                            channel=channel,
                            error_type=type(exc).__name__,
                        )
                logger.debug("redis_unsubscribed", channel=channel)

            if retry and self._has_local_recipients(conversation_id, target):
                try:
                    await asyncio.sleep(_SUBSCRIPTION_RETRY_SECONDS)
                except asyncio.CancelledError:
                    return

    def _start_sub(self, conversation_id: str, target: str):
        """Start a subscription loop task if Redis is available and not already running."""
        key = f"{conversation_id}:{target}"
        if key in self._sub_tasks and not self._sub_tasks[key].done():
            return
        if self._redis() is None:
            return
        task = asyncio.create_task(self._subscribe_loop(conversation_id, target))
        self._sub_tasks[key] = task

    def _stop_sub(self, conversation_id: str, target: str):
        """Cancel the subscription loop if no more local connections exist for this conv+target."""
        registry = (
            self.widget_connections if target == "widget"
            else self.admin_connections
        )
        if registry.get(conversation_id):
            return  # still have local connections — keep subscribing
        key = f"{conversation_id}:{target}"
        task = self._sub_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()

    # ── connect / disconnect ─────────────────────────────────────────────────

    async def connect_widget(
        self,
        websocket: WebSocket,
        conversation_id: str,
        *,
        subprotocol: str | None = None,
    ):
        await websocket.accept(subprotocol=subprotocol)
        self.widget_connections.setdefault(conversation_id, set()).add(websocket)
        self._start_sub(conversation_id, "widget")
        logger.info("widget_websocket_connected", conversation_id=conversation_id)

    async def connect_admin(
        self,
        websocket: WebSocket,
        conversation_id: str,
        *,
        subprotocol: str | None = None,
    ):
        # Read shared control before admitting the socket.  If Redis is
        # configured but unavailable, do not register a local socket that
        # might incorrectly believe it owns a fallback takeover state.
        is_human = await self.is_human_in_control(conversation_id)
        await websocket.accept(subprotocol=subprotocol)
        self.admin_connections.setdefault(conversation_id, set()).add(websocket)
        self._start_sub(conversation_id, "admin")
        logger.info("admin_websocket_connected", conversation_id=conversation_id)

        # Notify admin of current control state immediately on connect
        await self.send_to_admin(conversation_id, {
            "type": "control_status",
            "is_human_in_control": is_human,
        })

    async def disconnect_widget(self, websocket: WebSocket, conversation_id: str):
        conns = self.widget_connections.get(conversation_id, set())
        conns.discard(websocket)
        if not conns:
            self.widget_connections.pop(conversation_id, None)
        self._stop_sub(conversation_id, "widget")
        logger.info("widget_websocket_disconnected", conversation_id=conversation_id)

    async def disconnect_admin(self, websocket: WebSocket, conversation_id: str):
        conns = self.admin_connections.get(conversation_id, set())
        conns.discard(websocket)
        if not conns:
            self.admin_connections.pop(conversation_id, None)
        self._stop_sub(conversation_id, "admin")
        logger.info("admin_websocket_disconnected", conversation_id=conversation_id)

    # ── message fanout ───────────────────────────────────────────────────────

    async def send_to_widget(self, conversation_id: str, message: dict):
        """
        Deliver message to all widget connections for this conversation,
        across all API instances via Redis pub/sub.
        Local delivery happens immediately; Redis fans out to other instances.
        """
        await self._send_local(self.widget_connections, conversation_id, message)
        await self._publish(_channel(conversation_id, "widget"), message)

    async def send_to_admin(self, conversation_id: str, message: dict):
        """Same as send_to_widget but for admin connections."""
        await self._send_local(self.admin_connections, conversation_id, message)
        await self._publish(_channel(conversation_id, "admin"), message)

    # ── shared state — Redis hash with local fallback only when absent ───────

    async def set_human_control(self, conversation_id: str, is_active: bool):
        r = self._redis()
        if r is not None:
            try:
                await r.hset(
                    _state_key(conversation_id),
                    mapping={"is_human_in_control": "1" if is_active else "0"},
                )
                await r.expire(_state_key(conversation_id), _STATE_TTL)
                if is_active:
                    # Start a fresh buffer by deleting the old list
                    await r.delete(_buffer_key(conversation_id))
            except Exception as exc:
                logger.warning("redis_set_human_control_failed", error_type=type(exc).__name__)
                raise TakeoverStateUnavailableError("Human takeover state is unavailable") from exc
        else:
            self._local_control[conversation_id] = is_active
            if is_active:
                self._local_buffers[conversation_id] = []
        logger.info("human_control_updated", conversation_id=conversation_id, is_active=is_active)

    async def is_human_in_control(self, conversation_id: str) -> bool:
        r = self._redis()
        if r is not None:
            try:
                val = await r.hget(_state_key(conversation_id), "is_human_in_control")
                return val == "1"
            except Exception as exc:
                logger.warning("redis_get_human_control_failed", error_type=type(exc).__name__)
                raise TakeoverStateUnavailableError("Human takeover state is unavailable") from exc
        return self._local_control.get(conversation_id, False)

    async def register_agent_id(self, conversation_id: str, agent_id: str):
        r = self._redis()
        if r is not None:
            try:
                await r.hset(_state_key(conversation_id), mapping={"agent_id": agent_id})
                await r.expire(_state_key(conversation_id), _STATE_TTL)
                return
            except Exception as exc:
                logger.warning("redis_register_agent_id_failed", error_type=type(exc).__name__)
                raise TakeoverStateUnavailableError("Human takeover state is unavailable") from exc
        self._local_agent_ids[conversation_id] = agent_id

    async def get_agent_id(self, conversation_id: str) -> Optional[str]:
        r = self._redis()
        if r is not None:
            try:
                val = await r.hget(_state_key(conversation_id), "agent_id")
                return val
            except Exception as exc:
                logger.warning("redis_get_agent_id_failed", error_type=type(exc).__name__)
                raise TakeoverStateUnavailableError("Human takeover state is unavailable") from exc
        return self._local_agent_ids.get(conversation_id)

    async def buffer_takeover_message(self, conversation_id: str, role: str, content: str):
        entry = json.dumps({"role": role, "content": content})
        r = self._redis()
        if r is not None:
            try:
                await r.rpush(_buffer_key(conversation_id), entry)
                await r.expire(_buffer_key(conversation_id), _STATE_TTL)
                return
            except Exception as exc:
                logger.warning("redis_buffer_message_failed", error_type=type(exc).__name__)
                raise TakeoverStateUnavailableError("Human takeover state is unavailable") from exc
        buf = self._local_buffers.setdefault(conversation_id, [])
        buf.append({"role": role, "content": content})

    async def get_takeover_buffer(self, conversation_id: str) -> list:
        """Read buffered human-takeover turns without acknowledging them.

        Release control is a two-step operation: durable memory injection must
        finish before the buffer is deleted.  Returning a copy here lets a
        caller retry safely after a transient store failure instead of losing
        the intervening conversation.
        """
        r = self._redis()
        if r is not None:
            try:
                raw = await r.lrange(_buffer_key(conversation_id), 0, -1)
            except Exception as exc:
                logger.warning("redis_get_buffer_failed", error_type=type(exc).__name__)
                raise TakeoverStateUnavailableError("Human takeover history is unavailable") from exc
            try:
                messages = [json.loads(message) for message in raw]
                if not all(isinstance(message, dict) for message in messages):
                    raise TypeError("takeover buffer entries must be objects")
                return messages
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
                logger.warning("redis_takeover_buffer_invalid", error_type=type(exc).__name__)
                raise TakeoverBufferIntegrityError("Human takeover history is invalid") from exc
        return list(self._local_buffers.get(conversation_id, []))

    async def clear_takeover_buffer(self, conversation_id: str) -> None:
        """Acknowledge a buffer only after its turns are durably persisted."""
        r = self._redis()
        if r is not None:
            try:
                await r.delete(_buffer_key(conversation_id))
                return
            except Exception as exc:
                logger.warning("redis_clear_buffer_failed", error_type=type(exc).__name__)
                raise TakeoverStateUnavailableError("Takeover history acknowledgement is unavailable") from exc
        self._local_buffers.pop(conversation_id, None)

    async def purge_conversation_state(self, conversation_id: str) -> None:
        """Invalidate local and shared takeover state for a deleted subject."""
        for websocket in list(self.widget_connections.get(conversation_id, set())):
            try:
                await websocket.close(code=1008, reason="Conversation data deleted")
            except (RuntimeError, asyncio.CancelledError):
                pass
        for websocket in list(self.admin_connections.get(conversation_id, set())):
            try:
                await websocket.close(code=1008, reason="Conversation data deleted")
            except (RuntimeError, asyncio.CancelledError):
                pass
        self.widget_connections.pop(conversation_id, None)
        self.admin_connections.pop(conversation_id, None)
        self._stop_sub(conversation_id, "widget")
        self._stop_sub(conversation_id, "admin")
        self._local_control.pop(conversation_id, None)
        self._local_agent_ids.pop(conversation_id, None)
        self._local_buffers.pop(conversation_id, None)

        r = self._redis()
        if r is not None:
            try:
                await r.delete(_state_key(conversation_id), _buffer_key(conversation_id))
            except Exception as exc:
                # Mongo-side erasure is still authoritative.  A residual Redis
                # key cannot be reused because the session scope is revoked.
                logger.warning(
                    "redis_privacy_purge_failed",
                    conversation_id=conversation_id,
                    error_type=type(exc).__name__,
                )

    async def pop_takeover_buffer(self, conversation_id: str) -> list:
        """Compatibility helper for callers that explicitly need destructive read."""
        messages = await self.get_takeover_buffer(conversation_id)
        await self.clear_takeover_buffer(conversation_id)
        return messages


# Singleton
ws_manager = ConnectionManager()
