from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pactlyn.core.commitments import CommitmentService
from pactlyn.storage.models import (
    Commitment,
    CommitmentEvent,
    CommitmentRelationshipType,
    CommitmentStatus,
)


@dataclass(frozen=True)
class FollowThroughRecommendation:
    title: str
    explanation: str
    commitment_ids: tuple[str, ...]


class RecommendationEngine:
    """Produce explainable, local-only suggestions from commitment relationships."""

    def __init__(self, session: Session):
        self.session = session
        self.commitments = CommitmentService(session)

    def recommend(self, now: datetime | None = None, *, limit: int = 10) -> list[FollowThroughRecommendation]:
        now = now or datetime.now(UTC)
        recommendations: list[FollowThroughRecommendation] = []
        active = list(
            self.session.scalars(
                select(Commitment).where(
                    Commitment.status.notin_((CommitmentStatus.COMPLETED, CommitmentStatus.CANCELLED))
                )
            )
        )
        terminal = {
            CommitmentStatus.COMPLETED,
            CommitmentStatus.CANCELLED,
            CommitmentStatus.RESPONSE_RECEIVED,
        }
        for commitment in active:
            for relation, related in self.commitments.related(commitment.id):
                outgoing = relation.commitment_id == commitment.id
                incoming = relation.related_commitment_id == commitment.id
                if not outgoing and not incoming:
                    continue
                if relation.relationship == CommitmentRelationshipType.SUPERSEDES:
                    if incoming and related.status not in {CommitmentStatus.CANCELLED, CommitmentStatus.COMPLETED}:
                        # The older endpoint is no longer actionable while its
                        # replacement remains active.
                        break
                    continue
                if relation.relationship in {
                    CommitmentRelationshipType.BLOCKED_BY,
                    CommitmentRelationshipType.DEPENDS_ON,
                } and outgoing and related.status not in terminal:
                    recommendations.append(
                        FollowThroughRecommendation(
                            title=f"Blocked: {commitment.title}",
                            explanation=f"{commitment.title} depends on {related.title}, which is still {related.status.value}.",
                            commitment_ids=(commitment.id, related.id),
                        )
                    )
                elif relation.relationship == CommitmentRelationshipType.FOLLOWED_BY and incoming and related.status in terminal:
                    recommendations.append(
                        FollowThroughRecommendation(
                            title=f"Now possible: {commitment.title}",
                            explanation=f"The preceding commitment {related.title} is complete.",
                            commitment_ids=(commitment.id, related.id),
                        )
                    )
                elif (
                    relation.relationship == CommitmentRelationshipType.RESPONSE_REQUIRED_FROM
                    and outgoing
                ):
                    if related.status in terminal:
                        recommendations.append(
                            FollowThroughRecommendation(
                                title=f"Now possible: {commitment.title}",
                                explanation=f"The required response for {commitment.title} was received from {related.title}.",
                                commitment_ids=(commitment.id, related.id),
                            )
                        )
                    else:
                        recommendations.append(
                            FollowThroughRecommendation(
                                title=f"Conditional follow-up held: {commitment.title}",
                                explanation=f"{commitment.title} should wait for a response on {related.title} before it is recommended.",
                                commitment_ids=(commitment.id, related.id),
                            )
                        )
            if commitment.condition:
                related_conditions = [
                    (relation, related)
                    for relation, related in self.commitments.related(commitment.id)
                    if relation.commitment_id == commitment.id
                    and relation.relationship in {
                        CommitmentRelationshipType.DEPENDS_ON,
                        CommitmentRelationshipType.BLOCKED_BY,
                        CommitmentRelationshipType.RESPONSE_REQUIRED_FROM,
                    }
                ]
                if related_conditions and any(related.status not in terminal for _, related in related_conditions):
                    recommendations.append(
                        FollowThroughRecommendation(
                            title=f"Condition not met: {commitment.title}",
                            explanation=f"The condition for {commitment.title} has not been satisfied yet.",
                            commitment_ids=(commitment.id, related_conditions[0][1].id),
                        )
                    )
            if commitment.status == CommitmentStatus.WAITING and commitment.due_at and commitment.due_at <= now:
                recommendations.append(
                    FollowThroughRecommendation(
                        title=f"Follow up: {commitment.title}",
                        explanation=f"This waiting commitment reached its expected response time ({commitment.id}).",
                        commitment_ids=(commitment.id,),
                    )
                )
            postponements = self.session.scalar(
                select(func.count(CommitmentEvent.id)).where(
                    CommitmentEvent.commitment_id == commitment.id,
                    CommitmentEvent.event_type == "postponed",
                )
            ) or 0
            if postponements >= 2:
                recommendations.append(
                    FollowThroughRecommendation(
                        title=f"Review repeated postponement: {commitment.title}",
                        explanation=f"This commitment has been postponed {postponements} times.",
                        commitment_ids=(commitment.id,),
                    )
                )
        unique: list[FollowThroughRecommendation] = []
        seen: set[tuple[str, tuple[str, ...]]] = set()
        for recommendation in recommendations:
            key = (recommendation.title, recommendation.commitment_ids)
            if key not in seen:
                seen.add(key)
                unique.append(recommendation)
        return unique[:limit]
