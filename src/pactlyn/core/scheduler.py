from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from pactlyn.storage.models import Commitment, CommitmentStatus, Reminder, ReminderDelivery


class ReminderScheduler:
    """Persistent reminder evaluator; safe to call at launch and periodically."""

    def __init__(
        self,
        session: Session,
        notify: Callable[[str, str], None] | None = None,
        *,
        timezone_name: str = "UTC",
        quiet_hours_start: int | None = None,
        quiet_hours_end: int | None = None,
    ):
        self.session = session
        self.notify = notify or (lambda _title, _body: None)
        self.timezone = ZoneInfo(timezone_name)
        self.quiet_hours_start = quiet_hours_start
        self.quiet_hours_end = quiet_hours_end

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
            if self._in_quiet_hours(now):
                reminder.scheduled_at = self._quiet_hours_end(now)
                continue
            if commitment.status not in {CommitmentStatus.COMPLETED, CommitmentStatus.CANCELLED}:
                if commitment.due_at and commitment.due_at < now:
                    commitment.status = CommitmentStatus.OVERDUE
                self.notify("Pactlyn reminder", commitment.title)
                self.session.add(
                    ReminderDelivery(
                        reminder_id=reminder.id,
                        channel="desktop",
                        state="delivered",
                        delivered_at=now,
                    )
                )
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

    def _in_quiet_hours(self, now: datetime) -> bool:
        if self.quiet_hours_start is None or self.quiet_hours_end is None:
            return False
        hour = now.astimezone(self.timezone).hour
        if self.quiet_hours_start < self.quiet_hours_end:
            return self.quiet_hours_start <= hour < self.quiet_hours_end
        return hour >= self.quiet_hours_start or hour < self.quiet_hours_end

    def _quiet_hours_end(self, now: datetime) -> datetime:
        local = now.astimezone(self.timezone)
        target = local.replace(
            hour=self.quiet_hours_end or 0,
            minute=0,
            second=0,
            microsecond=0,
        )
        if target <= local:
            target += timedelta(days=1)
        return target.astimezone(UTC)
