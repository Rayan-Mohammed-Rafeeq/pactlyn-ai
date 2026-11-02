from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from pactlyn.storage.models import Commitment, CommitmentStatus, Reminder


class ReminderScheduler:
    """Persistent reminder evaluator; safe to call at launch and periodically."""

    def __init__(self, session: Session, notify: Callable[[str, str], None] | None = None):
        self.session = session
        self.notify = notify or (lambda _title, _body: None)

    def evaluate(self, now: datetime | None = None) -> list[Reminder]:
        now = now or datetime.now(UTC)
        # The application deliberately uses autoflush=False so UI reads do not
        # unexpectedly write. Flush explicitly before evaluating durable work.
        self.session.flush()
        reminders = list(self.session.scalars(select(Reminder).where(Reminder.dismissed.is_(False), Reminder.delivered_at.is_(None), Reminder.scheduled_at <= now)))
        for reminder in reminders:
            commitment = self.session.get(Commitment, reminder.commitment_id)
            if not commitment:
                reminder.dismissed = True
                continue
            if commitment.status not in {CommitmentStatus.COMPLETED, CommitmentStatus.CANCELLED}:
                if commitment.due_at and commitment.due_at < now:
                    commitment.status = CommitmentStatus.OVERDUE
                self.notify("Pactlyn reminder", commitment.title)
            reminder.delivered_at = now
        self.session.commit()
        return reminders

    def snooze(self, reminder_id: str, until: datetime) -> Reminder:
        reminder = self.session.get(Reminder, reminder_id)
        if not reminder:
            raise KeyError(f"Unknown reminder: {reminder_id}")
        reminder.snoozed_until = until
        reminder.delivered_at = None
        reminder.scheduled_at = until
        self.session.commit()
        return reminder
