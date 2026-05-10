"""
SourceStatusListener — PostgreSQL LISTEN/NOTIFY subscriber.

Maintains a dedicated asyncpg connection (completely independent of the
SQLAlchemy session pool) and subscribes to the `source_status_updates`
channel.  On every NOTIFY, the payload is parsed and logged.

Architecture notes:
- Do NOT share this connection with SQLAlchemy.
- asyncpg requires a plain `postgresql://` DSN (no driver prefix).
- `handle_notification` is an asyncpg callback — keep it non-blocking.
- Future hooks are marked with "# TODO: SSE" comments for easy search.
"""

import json
import asyncio
from collections import defaultdict

import asyncpg

from app.core.config import settings
from app.utils.logger import logger

CHANNEL_NAME = "source_status_updates"


class SourceStatusListener:
    """
    Persistent PostgreSQL LISTEN subscriber for source indexing events.

    Lifecycle:
        startup  → await listener.connect()
        shutdown → await listener.disconnect()

    The connection is kept alive for the full application lifetime.
    asyncpg will call `handle_notification` on every NOTIFY emitted by the
    database triggers defined in app/db/sql/source_status_triggers.sql.
    """

    def __init__(self) -> None:
        self._connection: asyncpg.Connection | None = None
        self._reconnect_task: asyncio.Task | None = None
        # source_id (str) → set of asyncio.Queue objects held by SSE handlers
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    # ------------------------------------------------------------------
    # Public lifecycle API
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open a dedicated asyncpg connection and start listening."""
        dsn = settings.ASYNC_DATABASE_URL
        try:
            self._connection = await asyncpg.connect(dsn)
            await self._connection.add_listener(CHANNEL_NAME, self._handle_notification)
            logger.info(
                "[SourceStatusListener] Connected. Listening on channel: %s",
                CHANNEL_NAME,
            )
        except Exception as exc:
            logger.error(
                "[SourceStatusListener] Failed to connect: %s", exc, exc_info=True
            )
            # Schedule a reconnect attempt so startup doesn't crash the app.
            self._schedule_reconnect()

    async def disconnect(self) -> None:
        """Remove listener and close the connection gracefully."""
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()

        if self._connection:
            try:
                await self._connection.remove_listener(CHANNEL_NAME, self._handle_notification)
                await self._connection.close()
                logger.info("[SourceStatusListener] Connection closed.")
            except Exception as exc:
                logger.warning(
                    "[SourceStatusListener] Error during disconnect: %s", exc
                )
            finally:
                self._connection = None

    # ------------------------------------------------------------------
    # SSE subscription management
    # ------------------------------------------------------------------

    def subscribe(self, source_id: str) -> asyncio.Queue:
        """
        Register an asyncio.Queue for a given source_id.

        The SSE route handler calls this, then awaits items from the returned
        queue.  Every matching PG NOTIFY will put a parsed dict onto it.

        Args:
            source_id: String UUID of the source to watch.

        Returns:
            asyncio.Queue that receives parsed notification dicts.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[source_id].add(queue)
        logger.info("[SourceStatusListener] SSE subscriber registered for source %s", source_id)
        return queue

    def unsubscribe(self, source_id: str, queue: asyncio.Queue) -> None:
        """
        Remove a previously registered queue.

        Should always be called in a `finally` block inside the SSE generator
        so the queue is cleaned up even if the client disconnects abruptly.

        Args:
            source_id: String UUID of the source.
            queue:     The exact Queue object returned by subscribe().
        """
        self._subscribers[source_id].discard(queue)
        if not self._subscribers[source_id]:
            del self._subscribers[source_id]
        logger.info("[SourceStatusListener] SSE subscriber removed for source %s", source_id)

    # ------------------------------------------------------------------
    # Notification handler
    # ------------------------------------------------------------------

    async def _handle_notification(
        self,
        connection: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """
        Called by asyncpg for every NOTIFY on `source_status_updates`.

        Parses the JSON payload and logs it.  This method is intentionally
        kept lightweight — heavy work (broadcasting, caching, queuing) will
        be added here in later phases.

        Args:
            connection: The asyncpg connection that received the notification.
            pid:        PostgreSQL backend PID that sent the NOTIFY.
            channel:    Channel name (always "source_status_updates").
            payload:    Raw JSON string from the trigger function.
        """
        try:
            data: dict = json.loads(payload)
        except json.JSONDecodeError as exc:
            logger.warning(
                "[SourceStatusListener] Received non-JSON payload on %s: %r — %s",
                channel,
                payload,
                exc,
            )
            return

        event = data.get("event", "unknown")
        source_id = str(data.get("source_id", "?"))

        logger.info(
            "[PG NOTIFY] channel=%s event=%s source_id=%s payload=%s",
            channel,
            event,
            source_id,
            data,
        )

        # Dispatch to all SSE queues waiting on this source_id
        queues = list(self._subscribers.get(source_id, set()))
        for q in queues:
            q.put_nowait(data)

    # ------------------------------------------------------------------
    # Reconnect logic (best-effort, does not block startup)
    # ------------------------------------------------------------------

    def _schedule_reconnect(self, delay: float = 5.0) -> None:
        """Schedule a background reconnect attempt after `delay` seconds."""
        loop = asyncio.get_event_loop()
        self._reconnect_task = loop.create_task(self._reconnect_loop(delay))

    async def _reconnect_loop(self, delay: float) -> None:
        """Retry connecting every `delay` seconds until successful."""
        while True:
            await asyncio.sleep(delay)
            logger.info("[SourceStatusListener] Attempting reconnect…")
            try:
                await self.connect()
                if self._connection:
                    return  # Connected — stop the loop.
            except Exception as exc:
                logger.error(
                    "[SourceStatusListener] Reconnect failed: %s", exc
                )


# ---------------------------------------------------------------------------
# Module-level singleton — imported by main.py lifespan hooks.
# ---------------------------------------------------------------------------
source_status_listener = SourceStatusListener()
