from __future__ import annotations

from typing import TypedDict

from pactlyn.core.commitments import CommitmentCandidate, CommitmentRelationshipCandidate


class PactlynState(TypedDict, total=False):
    run_id: str
    input_text: str
    timezone: str
    candidates: list[CommitmentCandidate]
    relationships: list[CommitmentRelationshipCandidate]
    selected_candidate: CommitmentCandidate
    needs_confirmation: bool
    confirmation: bool
    status: str
    explanation: str
    errors: list[str]
