from __future__ import annotations

from typing import TypedDict

from pactlyn.core.commitments import CommitmentCandidate


class PactlynState(TypedDict, total=False):
    run_id: str
    input_text: str
    timezone: str
    candidates: list[CommitmentCandidate]
    selected_candidate: CommitmentCandidate
    needs_confirmation: bool
    confirmation: bool
    status: str
    explanation: str
    errors: list[str]
