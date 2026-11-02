from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pactlyn.storage.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


class CommitmentType(enum.StrEnum):
    PERSONAL_TASK = "personal_task"
    WAITING_FOR = "waiting_for"
    FOLLOW_UP = "follow_up"
    DEADLINE = "deadline"
    EVENT = "event"


class CommitmentStatus(enum.StrEnum):
    DRAFT = "draft"
    NEEDS_CONFIRMATION = "needs_confirmation"
    ACTIVE = "active"
    WAITING = "waiting"
    RESPONSE_RECEIVED = "response_received"
    DUE_SOON = "due_soon"
    OVERDUE = "overdue"
    COMPLETED = "completed"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"


class EmailState(enum.StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class MemoryKind(enum.StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class UserProfile(Base):
    __tablename__ = "user_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class UserPreference(Base):
    __tablename__ = "user_preferences"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(120))
    value: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_preference"),)


class ModelConfiguration(Base):
    __tablename__ = "model_configurations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(80))
    model_name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_cloud: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class ProviderConfiguration(Base):
    __tablename__ = "provider_configurations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(80), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    non_secret_settings: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)


class ContactRelationship(Base):
    __tablename__ = "contact_relationships"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    relationship: Mapped[str] = mapped_column(String(120))
    context: Mapped[str] = mapped_column(Text, default="")


class ContactNote(Base):
    __tablename__ = "contact_notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class CommitmentRelationship(Base):
    __tablename__ = "commitment_relationships"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    commitment_id: Mapped[str] = mapped_column(ForeignKey("commitments.id", ondelete="CASCADE"), index=True)
    related_commitment_id: Mapped[str] = mapped_column(ForeignKey("commitments.id", ondelete="CASCADE"), index=True)
    relationship: Mapped[str] = mapped_column(String(80))


class ReminderDelivery(Base):
    __tablename__ = "reminder_deliveries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    reminder_id: Mapped[str] = mapped_column(ForeignKey("reminders.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(50))
    state: Mapped[str] = mapped_column(String(50))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Commitment(Base):
    __tablename__ = "commitments"
    __table_args__ = (Index("ix_commitments_status_due", "status", "due_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[CommitmentType] = mapped_column(Enum(CommitmentType), default=CommitmentType.PERSONAL_TASK)
    status: Mapped[CommitmentStatus] = mapped_column(Enum(CommitmentStatus), default=CommitmentStatus.NEEDS_CONFIRMATION)
    person: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="manual")
    evidence: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(default=0.0)
    needs_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    events: Mapped[list[CommitmentEvent]] = relationship(back_populates="commitment", cascade="all, delete-orphan")
    reminders: Mapped[list[Reminder]] = relationship(back_populates="commitment", cascade="all, delete-orphan")


class CommitmentEvent(Base):
    __tablename__ = "commitment_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    commitment_id: Mapped[str] = mapped_column(ForeignKey("commitments.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    commitment: Mapped[Commitment] = relationship(back_populates="events")


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (UniqueConstraint("commitment_id", "scheduled_at", name="uq_reminder_schedule"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    commitment_id: Mapped[str] = mapped_column(ForeignKey("commitments.id", ondelete="CASCADE"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    commitment: Mapped[Commitment] = relationship(back_populates="reminders")


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), index=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class EmailThread(Base):
    __tablename__ = "email_threads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_thread_id: Mapped[str | None] = mapped_column(String(300), unique=True, nullable=True)
    subject: Mapped[str] = mapped_column(String(500), default="")
    commitment_id: Mapped[str | None] = mapped_column(ForeignKey("commitments.id", ondelete="SET NULL"), nullable=True)
    association_confidence: Mapped[float] = mapped_column(default=0.0)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    messages: Mapped[list[EmailMessage]] = relationship(back_populates="thread", cascade="all, delete-orphan")


class EmailMessage(Base):
    __tablename__ = "email_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    thread_id: Mapped[str] = mapped_column(ForeignKey("email_threads.id", ondelete="CASCADE"), index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(300), unique=True, nullable=True)
    message_id_header: Mapped[str | None] = mapped_column(String(500), nullable=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sender: Mapped[str] = mapped_column(String(320))
    recipients: Mapped[list[str]] = mapped_column(JSON, default=list)
    subject: Mapped[str] = mapped_column(String(500), default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    thread: Mapped[EmailThread] = relationship(back_populates="messages")


class EmailAccount(Base):
    __tablename__ = "email_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(80), default="resend")
    inbound_address: Mapped[str | None] = mapped_column(String(320), nullable=True)
    sender_address: Mapped[str] = mapped_column(String(320))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class EmailDraft(Base):
    __tablename__ = "email_drafts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    commitment_id: Mapped[str | None] = mapped_column(ForeignKey("commitments.id", ondelete="SET NULL"), nullable=True)
    subject: Mapped[str] = mapped_column(String(500), default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    recipients: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class EmailSyncCursor(Base):
    __tablename__ = "email_sync_cursors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("email_accounts.id", ondelete="CASCADE"), unique=True)
    cursor: Mapped[str | None] = mapped_column(String(300), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailAttachment(Base):
    __tablename__ = "email_attachments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(ForeignKey("email_messages.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(150), default="application/octet-stream")
    local_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    downloaded: Mapped[bool] = mapped_column(Boolean, default=False)


class EmailSendAction(Base):
    __tablename__ = "email_send_actions"
    __table_args__ = (Index("ix_email_actions_state", "state"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    thread_id: Mapped[str | None] = mapped_column(ForeignKey("email_threads.id", ondelete="SET NULL"), nullable=True)
    commitment_id: Mapped[str | None] = mapped_column(ForeignKey("commitments.id", ondelete="SET NULL"), nullable=True)
    sender: Mapped[str] = mapped_column(String(320))
    recipients: Mapped[list[str]] = mapped_column(JSON, default=list)
    cc: Mapped[list[str]] = mapped_column(JSON, default=list)
    bcc: Mapped[list[str]] = mapped_column(JSON, default=list)
    reply_to: Mapped[str | None] = mapped_column(String(320), nullable=True)
    subject: Mapped[str] = mapped_column(String(500))
    body_text: Mapped[str] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[EmailState] = mapped_column(Enum(EmailState), default=EmailState.DRAFT, index=True)
    approval_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class MemoryRecord(Base):
    __tablename__ = "memory_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[MemoryKind] = mapped_column(Enum(MemoryKind), index=True)
    content: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    confidence: Mapped[float] = mapped_column(default=1.0)
    user_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    indexed: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class MemorySource(Base):
    __tablename__ = "memory_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_type: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryFeedback(Base):
    __tablename__ = "memory_feedback"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    memory_id: Mapped[str] = mapped_column(ForeignKey("memory_records.id", ondelete="CASCADE"), index=True)
    useful: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    operation: Mapped[str] = mapped_column(String(120), index=True)
    operation_id: Mapped[str] = mapped_column(String(36), index=True)
    detail: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    input_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="running")
    state_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentCheckpoint(Base):
    __tablename__ = "agent_checkpoints"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    node: Mapped[str] = mapped_column(String(100))
    state_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ToolExecution(Base):
    __tablename__ = "tool_executions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(120))
    input_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(50), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action_type: Mapped[str] = mapped_column(String(120))
    action_id: Mapped[str] = mapped_column(String(36), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
