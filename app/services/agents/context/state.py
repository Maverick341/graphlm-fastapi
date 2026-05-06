"""
Conversation state management.

Represents the runtime state of a chat session:
  - rolling summary (persistent in DB)
  - recent messages (current window)
  - token usage (computed)
  - compaction markers
"""

from dataclasses import dataclass, field
from uuid import UUID
from sqlalchemy.orm import Session as DBSession

from app.models.chat_message import ChatMessage, MessageRole
from app.core.config import settings


@dataclass
class ConversationState:
    """
    Runtime state for a conversation session.
    
    Persistent state (loaded from DB):
      - rolling_summary: Compressed history of old messages
      - rolling_summary_message_id: DB record ID for in-place updates
    
    Transient state (computed this request):
      - recent_messages: Current recent message window
      - older_messages_ids: IDs of messages that are "old" (eligible for compaction)
      - token_usage: Token estimate breakdown
      - compaction_performed: Whether compaction happened this request
      - messages_compacted_count: How many messages were summarized
    """
    session_id: UUID
    
    # Persistent state
    rolling_summary: str | None = None
    rolling_summary_message_id: UUID | None = None
    
    # Transient state
    recent_messages: list[dict] = field(default_factory=list)
    older_messages_ids: set[UUID] = field(default_factory=set)
    token_usage: dict = field(default_factory=dict)
    compaction_performed: bool = False
    messages_compacted_count: int = 0
    
    @classmethod
    async def load_from_db(
        cls,
        session_id: UUID,
        db: DBSession,
    ) -> "ConversationState":
        """
        Load conversation state from database.
        
        Steps:
          1. Fetch existing rolling summary (if any)
          2. Fetch all user/assistant messages
          3. Split into recent and older
          4. Return state object
        
        Args:
            session_id: Chat session UUID
            db: SQLAlchemy session
        
        Returns:
            ConversationState instance
        """
        # ── Fetch existing summary record ───────────────────────────────
        summary_record = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.chat_id == session_id,
                ChatMessage.role == MessageRole.system,
                ChatMessage.content.like("[SUMMARY]%"),
            )
            .order_by(ChatMessage.created_at.desc())
            .first()
        )
        
        # ── Fetch all user/assistant messages ────────────────────────────
        all_messages = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.chat_id == session_id,
                ChatMessage.role.in_([MessageRole.user, MessageRole.assistant]),
            )
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
        
        # ── Split into recent and older ─────────────────────────────────
        keep_recent = settings.CONTEXT_KEEP_RECENT
        
        if len(all_messages) <= keep_recent:
            older_messages_db = []
            recent_messages_db = all_messages
        else:
            older_messages_db = all_messages[:-keep_recent]
            recent_messages_db = all_messages[-keep_recent:]
        
        # Convert to dict format for agent
        recent_msgs = [
            {"role": msg.role.value, "content": msg.content}
            for msg in recent_messages_db
        ]
        
        older_ids = {msg.id for msg in older_messages_db}
        
        return cls(
            session_id=session_id,
            rolling_summary=summary_record.content if summary_record else None,
            rolling_summary_message_id=summary_record.id if summary_record else None,
            recent_messages=recent_msgs,
            older_messages_ids=older_ids,
        )
    
    def update_summary(
        self,
        new_summary: str,
        db: DBSession,
    ) -> None:
        """
        Update the rolling summary in the database.
        
        Either updates existing record in-place (if summary exists)
        or creates a new one (if this is the first compaction).
        
        Args:
            new_summary: The new summary text
            db: SQLAlchemy session
        """
        if self.rolling_summary_message_id:
            # Update existing record in-place (no duplicate rows)
            record = db.query(ChatMessage).get(self.rolling_summary_message_id)
            if record:
                record.content = new_summary
                db.commit()
        else:
            # Create new summary record
            record = ChatMessage(
                chat_id=self.session_id,
                role=MessageRole.system,
                content=new_summary,
            )
            db.add(record)
            db.commit()
            self.rolling_summary_message_id = record.id
        
        self.rolling_summary = new_summary


async def load_older_messages_for_compaction(
    session_id: UUID,
    older_ids: set[UUID],
    db: DBSession,
) -> list[dict]:
    """
    Load the full older messages for compaction/summarization.
    
    Args:
        session_id: Chat session UUID
        older_ids: Set of message IDs that are "old"
        db: SQLAlchemy session
    
    Returns:
        List of {"role": str, "content": str} dicts in chronological order
    """
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.id.in_(older_ids))
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    
    return [
        {"role": msg.role.value, "content": msg.content}
        for msg in messages
    ]
